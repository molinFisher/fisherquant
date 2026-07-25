import asyncio
import httpx
from pathlib import Path
import sys
import subprocess
import time
import signal


class MonitorVerifier:
    def __init__(self, port: int = 8899):
        self.port = port
        self.base_url = f"http://localhost:{port}"
        self.process = None

    def start_server(self):
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "fisher.monitor.app:app",
             "--host", "0.0.0.0", "--port", str(self.port)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        time.sleep(2)

    def stop_server(self):
        if self.process:
            self.process.terminate()
            self.process.wait(timeout=5)

    async def verify_all(self) -> dict:
        results = {}
        async with httpx.AsyncClient() as client:
            try:
                r = await client.get(f"{self.base_url}/dashboard", timeout=5)
                results["dashboard"] = r.status_code
            except Exception as e:
                results["dashboard"] = str(e)

            try:
                r = await client.get(f"{self.base_url}/login", timeout=5)
                results["login"] = r.status_code
            except Exception as e:
                results["login"] = str(e)

            try:
                async with httpx.AsyncClient() as ws_client:
                    async with ws_client.stream(
                        "GET", f"{self.base_url.replace('http', 'ws')}/ws/overview",
                        timeout=5,
                    ) as response:
                        results["ws_overview"] = response.status_code
            except Exception as e:
                results["ws_overview"] = str(e)

        return results

    def run(self) -> dict:
        self.start_server()
        try:
            return asyncio.run(self.verify_all())
        finally:
            self.stop_server()
