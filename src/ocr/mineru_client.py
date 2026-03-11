# src/ocr/mineru_client.py
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import requests
from requests.adapters import HTTPAdapter


@dataclass
class MinerUConfig:
    token: str
    base_url: str = "https://mineru.net/api/v4"

    model_version: str = "vlm"  # "vlm" or "pipeline"
    is_ocr: bool = False

    enable_formula: bool = True
    enable_table: bool = True
    language: str = "ch"

    poll_interval_sec: float = 2.0
    timeout_sec: float = 300.0

    request_timeout_sec: float = 60.0
    max_retries: int = 5
    retry_backoff_sec: float = 1.5
    throttle_sec: float = 0.15


class MinerUClient:
    """
    只做 HTTP：申请上传链接 -> PUT 上传 -> 轮询 batch -> 下载 full_zip_url
    关键：复用 requests.Session 以复用连接池，避免 WinError 10055
    """

    def __init__(self, cfg: MinerUConfig):
        self.cfg = cfg
        self.session = requests.Session()

        adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=0)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.cfg.token}",
            "Content-Type": "application/json",
            "Connection": "keep-alive",
        }

    def _sleep_throttle(self) -> None:
        if self.cfg.throttle_sec and self.cfg.throttle_sec > 0:
            time.sleep(self.cfg.throttle_sec)

    def _request_json(self, method: str, url: str, **kwargs) -> dict:
        last_err: Exception | None = None
        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                self._sleep_throttle()
                resp = self.session.request(
                    method,
                    url,
                    timeout=self.cfg.request_timeout_sec,
                    **kwargs,
                )
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_err = e
                time.sleep(self.cfg.retry_backoff_sec * attempt)

        raise RuntimeError(
            f"MinerU request failed after retries: {url}\nLast error: {last_err!r}"
        )

    def apply_upload_urls(self, files: List[Path]) -> tuple[str, List[str]]:
        url = f"{self.cfg.base_url}/file-urls/batch"
        payload = {
            "files": [{"name": f.name, "is_ocr": self.cfg.is_ocr} for f in files],
            "model_version": self.cfg.model_version,
            "enable_formula": self.cfg.enable_formula,
            "enable_table": self.cfg.enable_table,
            "language": self.cfg.language,
        }

        data = self._request_json("POST", url, headers=self._headers(), json=payload)
        if data.get("code") != 0:
            raise RuntimeError(f"MinerU apply upload urls failed: {data}")

        batch_id = data["data"]["batch_id"]
        put_urls = data["data"]["file_urls"]
        return batch_id, put_urls

    def upload_files(self, files: List[Path], put_urls: List[str]) -> None:
        if len(files) != len(put_urls):
            raise ValueError("files count != put_urls count")

        for f, put_url in zip(files, put_urls):
            with open(f, "rb") as fp:
                self._sleep_throttle()
                r = self.session.put(put_url, data=fp, timeout=300)
                r.raise_for_status()

    def get_batch_results(self, batch_id: str) -> dict:
        url = f"{self.cfg.base_url}/extract-results/batch/{batch_id}"
        data = self._request_json("GET", url, headers=self._headers())
        if data.get("code") != 0:
            raise RuntimeError(f"MinerU get batch results failed: {data}")
        return data["data"]

    def wait_for_done(self, batch_id: str, target_file_name: str) -> dict:
        deadline = time.time() + self.cfg.timeout_sec

        while time.time() < deadline:
            data = self.get_batch_results(batch_id)
            results = data.get("extract_result", [])

            item = next((x for x in results if x.get("file_name") == target_file_name), None)
            if not item:
                time.sleep(self.cfg.poll_interval_sec)
                continue

            state = item.get("state")
            if state == "done":
                return item
            if state == "failed":
                raise RuntimeError(f"MinerU parse failed: {item.get('err_msg') or item}")

            time.sleep(self.cfg.poll_interval_sec)

        raise TimeoutError(f"MinerU timeout after {self.cfg.timeout_sec}s, batch_id={batch_id}")

    def download_zip(self, full_zip_url: str) -> bytes:
        self._sleep_throttle()
        r = self.session.get(full_zip_url, timeout=300)
        r.raise_for_status()
        return r.content

    def parse_single_file(self, file_path: Path) -> bytes:
        upload_name = Path(file_path).name
        batch_id, put_urls = self.apply_upload_urls([Path(file_path)])
        self.upload_files([Path(file_path)], put_urls)
        item = self.wait_for_done(batch_id, upload_name)
        zip_url = item["full_zip_url"]
        return self.download_zip(zip_url)
