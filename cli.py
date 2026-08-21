#!/usr/bin/env python3
"""
Grok & x.ai Account Creator CLI
Automated account registration tool using Scrapling and Cloudflare bypass.
"""
import sys
import os
import argparse
import random
import string
import time
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich import print as rprint

from core.engine import StealthEngine
from core.auth import AccountCreator
from core.tempmail import TempMailClient
from core.mailbox_pool import MailboxPool, MailboxEntry
from core.exporter import AccountRecord, save_account, load_accounts
from core.tor_proxy import TorProxyManager
from core.proxyxoay import ProxyXoayManager
from config import (
    DEFAULT_JSON_OUTPUT,
    DEFAULT_TXT_OUTPUT,
    DEFAULT_FIRST_NAME,
    DEFAULT_LAST_NAME,
    DEFAULT_PASSWORD,
    DEFAULT_TOR_SOCKS_PORT,
    DEFAULT_TOR_CONTROL_PORT,
    DEFAULT_PROXYXOAY_KEY,
    DEFAULT_PROXYXOAY_NHAMANG,
    DEFAULT_PROXYXOAY_TINHTHANH,
    generate_random_name
)

console = Console()


def create_single_account(
    email: Optional[str] = None,
    password: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    use_tempmail: bool = False,
    proxy: Optional[str] = None,
    xai_proxy: Optional[str] = None,
    tempmail_proxy: Optional[str] = None,
    headless: bool = True,
    json_path: str = DEFAULT_JSON_OUTPUT,
    txt_path: str = DEFAULT_TXT_OUTPUT,
    index: int = 1,
    mailbox: Optional[MailboxEntry] = None,
) -> Optional[AccountRecord]:
    """
    Executes registration for a single account with decoupled proxies for xAI and TempMail.
    """
    # Resolve effective proxies
    effective_xai_proxy = xai_proxy or proxy
    effective_tempmail_proxy = tempmail_proxy or proxy

    tempmail_client: Optional[TempMailClient] = None

    # 1. Determine Email & Credentials
    if use_tempmail:
        with console.status("[bold cyan]Creating temporary email inbox (mail.gw / mail.tm)...", spinner="dots"):
            try:
                if mailbox is not None:
                    mbox_proxy = mailbox.proxy or effective_tempmail_proxy
                    tempmail_client = TempMailClient(proxy=mbox_proxy)
                    tempmail_client.set_token(mailbox.token)
                    email = mailbox.email
                else:
                    pool = MailboxPool(proxy_mgr=None, count=1, initial_proxy=effective_tempmail_proxy)
                    pool.prepare()
                    mailbox = pool.acquire(timeout=0)
                    if mailbox is None:
                        console.print("[red]✘ Failed to create tempmail:[/red] không đủ hòm thư Temp-Mail")
                        return None
                    mbox_proxy = mailbox.proxy or effective_tempmail_proxy
                    tempmail_client = TempMailClient(proxy=mbox_proxy)
                    tempmail_client.set_token(mailbox.token)
                    email = mailbox.email
                console.print(f"[green]✔[/green] Generated TempMail: [bold yellow]{email}[/bold yellow]")
            except Exception as e:
                console.print(f"[red]✘ Failed to create tempmail:[/red] {e}")
                return None
    else:
        if not email:
            email = Prompt.ask("[bold cyan]Enter Email for registration[/bold cyan]")

    if not first_name:
        first_name, last_name = generate_random_name()
    elif not last_name:
        last_name = DEFAULT_LAST_NAME
    if not password:
        password = DEFAULT_PASSWORD

    console.print(Panel(
        f"[bold]Target Email:[/bold] {email}\n"
        f"[bold]Name:[/bold] {first_name} {last_name}\n"
        f"[bold]Password:[/bold] {password}\n"
        f"[bold]xAI Proxy:[/bold] {effective_xai_proxy or 'None (Direct)'}\n"
        f"[bold]TempMail Proxy:[/bold] {(mailbox.proxy if mailbox else effective_tempmail_proxy) or 'None (Direct)'}\n"
        f"[bold]Engine:[/bold] Scrapling Stealth (Headless={headless})",
        title="[bold green]Registration Information[/bold green]",
        border_style="cyan"
    ))

    # 2. Launch Stealth Engine & AccountCreator with xAI Proxy
    engine = StealthEngine(headless=headless, proxy=effective_xai_proxy)
    creator = AccountCreator(engine=engine)

    try:
        with console.status("[bold cyan]Navigating to x.ai & Bypassing Cloudflare Turnstile...", spinner="dots"):
            creator.start_signup(email=email)
            console.print("[green]✔[/green] Cloudflare cleared! Verification OTP dispatched.")

        # 3. Retrieve or Prompt OTP
        otp_code: Optional[str] = None
        if use_tempmail and tempmail_client:
            with console.status("[bold cyan]Waiting for OTP email from x.ai...", spinner="dots"):
                otp_code = tempmail_client.fetch_otp_code(timeout_sec=120, page=creator.page)
                if otp_code:
                    console.print(f"[green]✔[/green] Received OTP automatically: [bold yellow]{otp_code}[/bold yellow]")
                else:
                    console.print("[yellow]⚠ Auto-OTP timeout. Please check manually.[/yellow]")

        if not otp_code:
            otp_code = Prompt.ask("[bold yellow]Enter 6-digit OTP code sent to your email[/bold yellow]")

        # 4. Submit OTP & Complete Registration
        with console.status("[bold cyan]Submitting OTP and setting up password...", spinner="dots"):
            creator.submit_otp(code=otp_code)
            record = creator.complete_registration(
                first_name=first_name,
                last_name=last_name,
                password=password
            )

        # 5. Save and Export
        save_account(record, json_path=json_path, txt_path=txt_path)
        console.print(Panel(
            f"[bold green]✔ Account Created Successfully![/bold green]\n\n"
            f"[bold]Email:[/bold] {record.email}\n"
            f"[bold]Password:[/bold] {record.password}\n"
            f"[bold]User ID:[/bold] {record.user_id}\n"
            f"[bold]Session ID:[/bold] {record.session_id}\n"
            f"[bold]SSO Cookie:[/bold] {record.sso_cookie[:40]}... (saved in full)\n"
            f"[bold]Saved To:[/bold] {json_path} and {txt_path}",
            title="[bold green]Success[/bold green]",
            border_style="green"
        ))
        return record

    except Exception as e:
        console.print(f"[bold red]✘ Registration failed:[/bold red] {e}")
        return None
    finally:
        engine.close()


def main():
    parser = argparse.ArgumentParser(
        description="Grok & x.ai Automated Account Creator CLI (Powered by Scrapling)"
    )
    parser.add_argument("--email", "-e", type=str, help="Email address to register")
    parser.add_argument("--password", "-p", type=str, default=DEFAULT_PASSWORD, help="Password for the new account")
    parser.add_argument("--first-name", type=str, default=None, help="Given name (default: auto random formula User_XXYY, e.g. User_01AI)")
    parser.add_argument("--last-name", type=str, default=None, help="Family name")
    parser.add_argument("--tempmail", "-t", action="store_true", help="Auto-generate disposable email & fetch OTP via API")
    parser.add_argument("--proxy", type=str, help="Default Proxy URL (applied to both xAI and TempMail if not specified individually)")
    parser.add_argument("--xai-proxy", type=str, help="Dedicated Proxy URL for xAI / Grok browser registration")
    parser.add_argument("--tempmail-proxy", type=str, help="Dedicated Proxy URL for TempMail API / OTP retrieval")
    parser.add_argument("--tempmail-tor", action="store_true", help="Route TempMail specifically through Tor SOCKS5 with Stream Isolation")
    parser.add_argument("--tor", action="store_true", help="Route traffic through local Tor SOCKS5 proxy with auto IP rotation")
    parser.add_argument("--tor-socks", type=int, default=DEFAULT_TOR_SOCKS_PORT, help="Tor SOCKS5 port (default: 9050)")
    parser.add_argument("--tor-control", type=int, default=DEFAULT_TOR_CONTROL_PORT, help="Tor Control port (default: 9051)")
    parser.add_argument("--proxyxoay", action="store_true", help="Use ProxyXoay residential rotating proxy")
    parser.add_argument("--proxy-key", type=str, default=DEFAULT_PROXYXOAY_KEY, help="ProxyXoay API key")
    parser.add_argument("--proxy-nhamang", type=str, default=DEFAULT_PROXYXOAY_NHAMANG, help="ProxyXoay network (random/viettel/vnpt/fpt)")
    parser.add_argument("--proxy-tinhthanh", type=str, default=DEFAULT_PROXYXOAY_TINHTHANH, help="ProxyXoay province (0 for random)")
    parser.add_argument("--headful", action="store_true", help="Run with visible browser window (default: headless)")
    parser.add_argument("--output-json", type=str, default=DEFAULT_JSON_OUTPUT, help="Path for JSON accounts output")
    parser.add_argument("--output-txt", type=str, default=DEFAULT_TXT_OUTPUT, help="Path for TXT accounts output")
    parser.add_argument("--list", "-l", action="store_true", help="List all saved accounts")
    parser.add_argument("--count", "-c", type=int, default=1, help="Number of accounts to create (batch loop mode)")
    parser.add_argument("--threads", "-j", type=int, default=1, help="Number of concurrent threads (default: 1, e.g. 3 or 5)")

    args = parser.parse_args()

    # List saved accounts
    if args.list:
        accounts = load_accounts(json_path=args.output_json)
        if not accounts:
            console.print("[yellow]No accounts found in accounts.json[/yellow]")
            return
        table = Table(title=f"Saved Grok Accounts ({len(accounts)})")
        table.add_column("Email", style="cyan")
        table.add_column("Password", style="magenta")
        table.add_column("User ID", style="green")
        table.add_column("SSO Cookie", style="yellow")
        table.add_column("Status", style="bold green")
        for acc in accounts:
            sso_preview = (acc.get("sso_cookie", "")[:25] + "...") if acc.get("sso_cookie") else "None"
            table.add_row(
                acc.get("email", ""),
                acc.get("password", ""),
                acc.get("user_id", "") or "N/A",
                sso_preview,
                acc.get("status", "active")
            )
        console.print(table)
        return

    tor_mgr: Optional[TorProxyManager] = None
    proxyxoay_mgr: Optional[ProxyXoayManager] = None
    xai_active_proxy: Optional[str] = args.xai_proxy or args.proxy
    tempmail_active_proxy: Optional[str] = args.tempmail_proxy or args.proxy

    # Check if Tor is requested (globally or specifically for TempMail)
    use_tor_tempmail = args.tempmail_tor or (args.tor and not args.tempmail_proxy)
    if use_tor_tempmail or args.tor:
        tor_mgr = TorProxyManager(socks_port=args.tor_socks, control_port=args.tor_control)
        with console.status("[bold cyan]Connecting to Tor SOCKS5 proxy...", spinner="dots"):
            ok, ip, details = tor_mgr.check_connection(timeout_sec=6)
            if ok and ip:
                country = details.get("country", "") if details else ""
                console.print(f"[bold green]✔ Connected to Tor Network![/bold green] Exit IP: [bold yellow]{ip}[/bold yellow] ({country})")
                if args.tor and not args.xai_proxy and not args.proxyxoay:
                    xai_active_proxy = tor_mgr.proxy_url
                if use_tor_tempmail:
                    tempmail_active_proxy = tor_mgr.proxy_url
            else:
                console.print(f"[bold red]✘ Could not connect to Tor proxy at {tor_mgr.proxy_url}[/bold red].")

    # Check ProxyXoay for xAI
    use_proxyxoay = args.proxyxoay or (args.proxy_key and not args.tor and not args.xai_proxy and not args.proxy)
    if use_proxyxoay:
        proxyxoay_mgr = ProxyXoayManager(
            api_key=args.proxy_key,
            nhamang=args.proxy_nhamang,
            tinhthanh=args.proxy_tinhthanh
        )
        with console.status("[bold cyan]Connecting to ProxyXoay (proxyxoay.shop)...", spinner="dots"):
            ok, p_url, p_data = proxyxoay_mgr.get_proxy(timeout_sec=10)
            if ok and p_url:
                ip = p_data.get("ip") or p_url
                isp = p_data.get("Nha Mang", "")
                loc = p_data.get("Vi Tri", "")
                console.print(f"[bold green]✔ Connected to ProxyXoay for xAI![/bold green] IP: [bold yellow]{ip}[/bold yellow] ({isp.upper()} - {loc})")
                xai_active_proxy = p_url
            else:
                msg = p_data.get("message") or p_data.get("error") or "Failed"
                console.print(f"[bold yellow]⚠ ProxyXoay warning: {msg}[/bold yellow]")

    # Decoupled proxy display
    console.print(Panel(
        f"[bold cyan]⚡ Grok & x.ai Automated Account Creator ⚡[/bold cyan]\n"
        f"[dim]Bypassing Cloudflare Turnstile & gRPC-Web Auth using Scrapling[/dim]\n\n"
        f"[bold]xAI Sign-up Channel:[/bold] {xai_active_proxy or 'Direct (No Proxy)'}\n"
        f"[bold]TempMail OTP Channel:[/bold] {('Tor SOCKS5 (Stream Isolation)' if (tor_mgr and use_tor_tempmail) else (tempmail_active_proxy or 'Direct'))}",
        border_style="cyan"
    ))

    num_threads = min(max(1, args.threads), 10)
    if num_threads > 1 and args.count > 1:
        console.print(f"[bold green]⚡ High-Speed Multi-Threading Mode: {num_threads} Concurrent Threads active![/bold green]")

        # Pre-create a Temp-Mail mailbox pool (serialized) before firing threads
        pool: Optional[MailboxPool] = None
        if args.tempmail:
            tm_mgr = tor_mgr if (use_tor_tempmail and tor_mgr) else proxyxoay_mgr
            with console.status(f"[bold cyan]Đang tạo hòm thư Temp-Mail #1/{args.count} (serialized)...", spinner="dots"):
                pool = MailboxPool(
                    proxy_mgr=tm_mgr,
                    count=args.count,
                    stopped=None,
                    initial_proxy=tempmail_active_proxy if not tm_mgr else None
                )
                made = pool.prepare()
            if made < args.count:
                console.print(
                    f"[yellow]⚠ Cảnh báo: Chỉ tạo được {made}/{args.count} hòm thư Temp-Mail. "
                    f"Các tài khoản vượt quá số hòm thư sẽ thất bại với 'không đủ hòm thư Temp-Mail' "
                    f"thay vì spam 429.[/yellow]"
                )
            else:
                console.print(f"[green]✔ Đã tạo xong {made}/{args.count} hòm thư Temp-Mail (serialized).[/green]")

        from concurrent.futures import ThreadPoolExecutor
        def worker(idx):
            mailbox = None
            if pool is not None:
                mailbox = pool.acquire(timeout=0)
                if mailbox is None:
                    console.print(f"[red]✘ [#{idx+1}/{args.count}] Thất bại: không đủ hòm thư Temp-Mail.[/red]")
                    return None
            return create_single_account(
                email=args.email,
                password=args.password,
                first_name=args.first_name,
                last_name=args.last_name,
                use_tempmail=args.tempmail,
                xai_proxy=xai_active_proxy,
                tempmail_proxy=tempmail_active_proxy,
                headless=not args.headful,
                json_path=args.output_json,
                txt_path=args.output_txt,
                index=idx+1,
                mailbox=mailbox
            )
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            list(executor.map(worker, range(args.count)))
    else:
        # Run creation sequentially
        for i in range(args.count):
            if args.count > 1:
                console.print(f"\n[bold magenta]=== Creating Account #{i+1} of {args.count} ===[/bold magenta]")

            # Rotate Proxy on subsequent iterations
            if i > 0:
                if proxyxoay_mgr:
                    with console.status("[bold cyan]Rotating ProxyXoay residential IP for xAI...", spinner="dots"):
                        rot_ok, new_p, p_data = proxyxoay_mgr.get_proxy(force_rotate=True)
                        if rot_ok and new_p:
                            ip = p_data.get("ip") or new_p
                            console.print(f"[bold green]✔ Rotated to new Residential IP for xAI:[/bold green] [bold yellow]{ip}[/bold yellow]")
                            xai_active_proxy = new_p

                if tor_mgr and (use_tor_tempmail or args.tor):
                    tempmail_active_proxy = tor_mgr.get_isolated_proxy_url(f"seq_worker_{i}")

            create_single_account(
                email=args.email,
                password=args.password,
                first_name=args.first_name,
                last_name=args.last_name,
                use_tempmail=args.tempmail,
                xai_proxy=xai_active_proxy,
                tempmail_proxy=tempmail_active_proxy,
                headless=not args.headful,
                json_path=args.output_json,
                txt_path=args.output_txt,
                index=i+1
            )
            if i < args.count - 1:
                time.sleep(1)


if __name__ == "__main__":
    main()
