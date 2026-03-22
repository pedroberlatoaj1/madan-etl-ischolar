"""
monitor.py — Entrypoint principal do pipeline ETL iScholar.

Fica em execução contínua monitorando a pasta /notas_pedagogico.
Quando um arquivo CSV/Excel é modificado e salvo, este módulo:
  1. aplica debounce por arquivo;
  2. aguarda o arquivo ficar estável (acessível + tamanho e mtime constantes);
  3. calcula um hash (SHA-256) do conteúdo;
  4. registra um job no SQLite (job_store.py) com esse hash.

A transformação dos dados e o envio ao iScholar ficam a cargo do worker
(`worker.py`), que consome os jobs pendentes.

Estratégia de debounce:
  Cada arquivo modificado agenda um timer de DEBOUNCE_SEGUNDOS.
  Se o arquivo for salvo novamente antes do timer expirar (ex: Excel ainda
  gravando), o timer é resetado. O job só é criado quando o arquivo
  para de ser modificado.

Uso:
  python monitor.py
  python monitor.py --pasta /outro/caminho  (sobrescreve config)
"""

from __future__ import annotations

import argparse
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import signal
import sys
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from config import config
from job_store import JobStoreError, criar_job_com_idempotencia
from logger import configurar_logger
from utils.hash_utils import sha256_file

log = configurar_logger("etl.monitor")


# ---------------------------------------------------------------------------
# Handler do Watchdog com debounce por arquivo
# ---------------------------------------------------------------------------

class ManipuladorNotasPedagogico(FileSystemEventHandler):
    """
    Escuta eventos de criação e modificação de arquivos na pasta monitorada.

    Debounce: mantém um timer por arquivo. Cada novo evento reinicia o timer.
    Quando o timer expira (arquivo "parou de ser salvo"), o pipeline é disparado.
    Recebe dependências no construtor em vez de consultar config diretamente.
    """

    def __init__(
        self,
        *,
        debounce_segundos: float,
        extensoes_suportadas: list[str],
        stability_required_checks: int,
        stability_check_interval: float,
    ):
        super().__init__()
        self._debounce_segundos = debounce_segundos
        self._extensoes_suportadas = frozenset(ext.lower() for ext in extensoes_suportadas)
        self._stability_required_checks = stability_required_checks
        self._stability_check_interval = stability_check_interval
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    # --- Filtragem de extensão ---

    def _extensao_suportada(self, caminho: str) -> bool:
        ext = Path(caminho).suffix.lower()
        return ext in self._extensoes_suportadas

    def _arquivo_temporario(self, caminho: str) -> bool:
        """
        Ignora arquivos temporários criados pelo Excel (~$arquivo.xlsx)
        ou pelo LibreOffice (.~lock.arquivo.xlsx#).
        """
        nome = Path(caminho).name
        return nome.startswith("~$") or nome.startswith(".~lock.")

    # --- Agendamento com debounce ---

    def _agendar_pipeline(self, caminho: str) -> None:
        """Cancela timer anterior (se existir) e agenda novo para este arquivo."""
        with self._lock:
            timer_existente = self._timers.get(caminho)
            if timer_existente:
                timer_existente.cancel()
                log.debug(
                    "⏱️  Debounce resetado para '%s' (novo evento recebido).",
                    Path(caminho).name,
                )

            novo_timer = threading.Timer(
                interval=self._debounce_segundos,
                function=self._disparar_pipeline,
                args=(caminho,),
            )
            novo_timer.daemon = True
            novo_timer.start()
            self._timers[caminho] = novo_timer

        log.debug(
            "⏳ Pipeline agendado em %.1fs para: %s",
            self._debounce_segundos,
            Path(caminho).name,
        )

    def _disparar_pipeline(self, caminho: str) -> None:
        """
        Executado pelo timer após o debounce expirar.

        Nesta etapa apenas criamos um job na fila (SQLite), sem transformar
        nem enviar nada diretamente ao iScholar.
        """
        with self._lock:
            self._timers.pop(caminho, None)

        if not self._aguardar_arquivo_estavel(caminho):
            log.warning(
                "⚠️  Arquivo '%s' não estabilizou após espera. Ignorando evento.",
                Path(caminho).name,
            )
            return

        nome_arquivo = Path(caminho).name
        log.info("📦 Arquivo estável após debounce: %s", nome_arquivo)

        try:
            content_hash = sha256_file(caminho)
            log.info(
                "🔑 Hash calculado para '%s': %s",
                nome_arquivo,
                content_hash,
            )

            job = criar_job_com_idempotencia(
                source_type="local_file",
                source_identifier=caminho,
                content_hash=content_hash,
                total_records=None,
            )

            if job.status == "skipped":
                log.info(
                    "⏭️ Job %s criado como skipped para '%s' (conteúdo já processado anteriormente).",
                    job.id,
                    nome_arquivo,
                )
            else:
                log.info(
                    "📌 Job %s criado como pending para '%s'.",
                    job.id,
                    nome_arquivo,
                )

        except FileNotFoundError as exc:
            log.warning(
                "🗑️  Arquivo '%s' removido antes de calcular hash: %s",
                nome_arquivo,
                exc,
            )
        except JobStoreError as exc:
            log.error(
                "❌ Falha ao registrar job no SQLite para '%s': %s",
                nome_arquivo,
                exc,
            )
        except Exception as exc:
            log.exception(
                "💣 Erro inesperado ao criar job para '%s': %s",
                nome_arquivo,
                exc,
            )

    def _aguardar_arquivo_estavel(self, caminho: str) -> bool:
        """
        Considera o arquivo estável apenas quando:
        - for possível abri-lo (sem lock);
        - tamanho e mtime permanecerem iguais por stability_required_checks
          verificações consecutivas, espaçadas por stability_check_interval.
        """
        intervalo = self._stability_check_interval
        required = self._stability_required_checks
        stable_count = 0
        last_size: int | None = None
        last_mtime: float | None = None
        max_tentativas = 60

        for tentativa in range(max_tentativas):
            try:
                st = os.stat(caminho)
                size, mtime = st.st_size, st.st_mtime
                with open(caminho, "rb"):
                    pass
            except (FileNotFoundError, PermissionError, OSError) as e:
                log.debug(
                    "   Arquivo inacessível (tentativa %d): %s. Aguardando %.1fs...",
                    tentativa + 1, e, intervalo,
                )
                stable_count = 0
                last_size = last_mtime = None
                time.sleep(intervalo)
                continue

            if last_size is not None and last_mtime is not None:
                if size == last_size and mtime == last_mtime:
                    stable_count += 1
                    if stable_count >= required:
                        return True
                    log.debug(
                        "   Estabilidade %d/%d para '%s'. Aguardando %.1fs...",
                        stable_count, required, Path(caminho).name, intervalo,
                    )
                else:
                    stable_count = 1
                    log.debug(
                        "   Tamanho ou mtime alterado para '%s'. Reiniciando contagem.",
                        Path(caminho).name,
                    )
            else:
                stable_count = 1

            last_size, last_mtime = size, mtime
            time.sleep(intervalo)

        return False

    # --- Callbacks do Watchdog ---

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        caminho = os.path.abspath(event.src_path)
        if self._arquivo_temporario(caminho) or not self._extensao_suportada(caminho):
            return
        log.debug("📄 Arquivo CRIADO detectado: %s", Path(caminho).name)
        self._agendar_pipeline(caminho)

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        caminho = os.path.abspath(event.src_path)
        if self._arquivo_temporario(caminho) or not self._extensao_suportada(caminho):
            return
        log.debug("✏️  Arquivo MODIFICADO detectado: %s", Path(caminho).name)
        self._agendar_pipeline(caminho)

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        destino = os.path.abspath(event.dest_path)
        if self._arquivo_temporario(destino) or not self._extensao_suportada(destino):
            return
        log.debug(
            "↪️  Arquivo RENOMEADO/MOVIDO detectado: %s → %s",
            Path(event.src_path).name,
            Path(destino).name,
        )
        self._agendar_pipeline(destino)


# ---------------------------------------------------------------------------
# Inicialização e loop principal
# ---------------------------------------------------------------------------

def iniciar_monitoramento(
    pasta_notas: str,
    debounce_seconds: float,
    stability_required_checks: int,
    stability_check_interval: float,
    *,
    extensoes_suportadas: list[str] | None = None,
) -> None:
    """
    Inicia o Observer do Watchdog e mantém o processo vivo.

    Args:
        pasta_notas: Caminho da pasta a monitorar.
        debounce_seconds: Tempo de espera após último evento antes de processar.
        stability_required_checks: Verificações consecutivas estáveis para considerar arquivo pronto.
        stability_check_interval: Intervalo em segundos entre cada verificação de estabilidade.
        extensoes_suportadas: Lista de extensões (ex: [".csv", ".xlsx"]). Se None, usa config.
    """
    pasta = os.path.abspath(pasta_notas)
    ext = extensoes_suportadas or list(config.EXTENSOES_SUPORTADAS)

    if not os.path.isdir(pasta):
        log.info("📁 Pasta '%s' não encontrada. Criando...", pasta)
        os.makedirs(pasta, exist_ok=True)

    handler = ManipuladorNotasPedagogico(
        debounce_segundos=debounce_seconds,
        extensoes_suportadas=ext,
        stability_required_checks=stability_required_checks,
        stability_check_interval=stability_check_interval,
    )
    observer = Observer()
    observer.schedule(handler, path=pasta, recursive=False)

    log.info("👀 Iniciando monitoramento da pasta: %s", pasta)
    log.info("   Extensões monitoradas : %s", ext)
    log.info("   Debounce configurado  : %.1fs", debounce_seconds)
    log.info(
        "   Estabilidade de arquivo : %d verificações a cada %.1fs",
        stability_required_checks,
        stability_check_interval,
    )
    log.info("   Pressione Ctrl+C para encerrar.")
    log.info("-" * 60)

    observer.start()

    def encerrar(signum, frame):
        log.info("\n🛑 Sinal de encerramento recebido. Parando monitor...")
        observer.stop()

    signal.signal(signal.SIGINT, encerrar)
    signal.signal(signal.SIGTERM, encerrar)

    try:
        while observer.is_alive():
            observer.join(timeout=1)
    finally:
        observer.join()
        log.info("✅ Monitor encerrado com sucesso.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parsear_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor ETL de notas pedagógicas → iScholar",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--pasta",
        default=config.PASTA_NOTAS,
        help="Caminho da pasta a ser monitorada.",
    )
    parser.add_argument(
        "--debounce",
        type=float,
        default=config.DEBOUNCE_SEGUNDOS,
        help="Tempo de espera (segundos) antes de processar após último evento.",
    )
    parser.add_argument(
        "--stability-checks",
        type=int,
        default=config.FILE_STABILITY_REQUIRED_CHECKS,
        help="Verificações consecutivas estáveis para considerar arquivo pronto.",
    )
    parser.add_argument(
        "--stability-interval",
        type=float,
        default=config.FILE_STABILITY_CHECK_INTERVAL,
        help="Intervalo em segundos entre verificações de estabilidade.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parsear_args()

    iniciar_monitoramento(
        pasta_notas=args.pasta,
        debounce_seconds=args.debounce,
        stability_required_checks=args.stability_checks,
        stability_check_interval=args.stability_interval,
    )
