#!/usr/bin/env python3
"""
Hồi sinh toàn bộ 865 tài khoản xAI / Grok chết trong accounts.json.
Sử dụng đa tầng: OAuth Refresh -> SSO Session Minting -> Password Login Recovery.
Tự động ping test grok-4.6 (HTTP 200) và xuất ra 'grok_router_accounts.json'.
"""
import sys
import os
import argparse
import logging
from rich.console import Console
from rich.panel import Panel

from core.reviver import AccountReviveManager
from core.proxyxoay import ProxyXoayManager
from config import DEFAULT_JSON_OUTPUT, DEFAULT_TXT_OUTPUT, DEFAULT_PROXYXOAY_KEY

console = Console()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Hồi sinh toàn bộ tài khoản xAI / Grok chết")
    parser.add_argument("--threads", "-j", type=int, default=5, help="Số luồng chạy song song (mặc định: 5)")
    parser.add_argument("--proxy-key", type=str, default=DEFAULT_PROXYXOAY_KEY, help="ProxyXoay API key")
    parser.add_argument("--direct", action="store_true", help="Chạy không dùng proxy (Direct mode)")
    parser.add_argument("--json", type=str, default=DEFAULT_JSON_OUTPUT, help="Đường dẫn accounts.json")
    parser.add_argument("--txt", type=str, default=DEFAULT_TXT_OUTPUT, help="Đường dẫn accounts.txt")

    args = parser.parse_args()

    proxy_url = None
    if not args.direct and args.proxy_key:
        px = ProxyXoayManager(api_key=args.proxy_key)
        ok, p, data = px.get_proxy()
        if ok and p:
            proxy_url = p
            ip = data.get("ip") or p
            console.print(f"[bold green]✔ Kết nối ProxyXoay thành công:[/bold green] [yellow]{ip}[/yellow]")

    console.print(Panel(
        f"[bold cyan]⚡ TIẾN TRÌNH HỒI SINH TÀI KHOẢN GROK / X.AI ⚡[/bold cyan]\n\n"
        f"[bold]Tập tin nguồn:[/bold] {args.json}\n"
        f"[bold]Số luồng song song:[/bold] {args.threads}\n"
        f"[bold]Proxy:[/bold] {proxy_url or 'Direct (Trực tiếp)'}\n"
        f"[bold]Quy trình:[/bold] OAuth Refresh ➔ SSO Browser Minting ➔ Password Login ➔ Ping Test (grok-4.6)",
        border_style="cyan"
    ))

    reviver = AccountReviveManager(json_path=args.json, txt_path=args.txt)
    
    def on_progress(st):
        pass

    reviver.run_revival(max_workers=args.threads, proxy=proxy_url, on_progress=on_progress)

    for log in reviver.logs:
        if "✔" in log:
            console.print(f"[bold green]{log}[/bold green]")
        elif "✘" in log:
            console.print(f"[bold red]{log}[/bold red]")
        else:
            console.print(f"[cyan]{log}[/cyan]")


if __name__ == "__main__":
    main()
