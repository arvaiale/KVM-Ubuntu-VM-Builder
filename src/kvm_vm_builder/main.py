"""KVM Ubuntu VM Builder - Phase 1."""

from __future__ import annotations

import argparse
import getpass
import ipaddress
import os
import re
import sys

import paramiko

TEMP_ISO_DIR = "temp"
MIN_STORAGE_RESERVE_GB = 5


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or (default or "")


def ask_int(prompt: str, default: int) -> int:
    while True:
        value = ask(prompt, str(default))
        try:
            number = int(value)
            if number > 0:
                return number
        except ValueError:
            pass
        print("Please enter a positive integer.")


def validate_vm_name(name: str) -> None:
    if not name or len(name) > 63:
        raise ValueError("VM name must contain 1-63 characters.")
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    if any(char not in allowed for char in name):
        raise ValueError("VM name may contain only letters, numbers, '-' and '_'.")
    if name[0] in "-_":
        raise ValueError("VM name must not start with '-' or '_'.")


def validate_hostname(hostname: str) -> None:
    if not hostname or len(hostname) > 253:
        raise ValueError("Hostname must contain 1-253 characters.")
    labels = hostname.rstrip(".").split(".")
    if any(
        not label
        or len(label) > 63
        or label[0] == "-"
        or label[-1] == "-"
        or not re.fullmatch(r"[A-Za-z0-9-]+", label)
        for label in labels
    ):
        raise ValueError(f"Invalid hostname: {hostname}")


def validate_ip(value: str) -> None:
    try:
        ipaddress.ip_interface(value)
    except ValueError as exc:
        raise ValueError(f"Invalid IP/prefix: {value}") from exc


def validate_ip_address(value: str, field: str) -> None:
    try:
        ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {field}: {value}") from exc


def validate_dns_servers(value: str) -> None:
    servers = [item.strip() for item in value.split(",") if item.strip()]
    if not servers:
        raise ValueError("At least one DNS server is required.")
    for server in servers:
        try:
            ipaddress.ip_address(server)
        except ValueError as exc:
            raise ValueError(f"Invalid DNS server: {server}") from exc


def validate_ntp_servers(value: str) -> None:
    servers = [item.strip() for item in value.split(",") if item.strip()]
    if not servers:
        raise ValueError("At least one NTP server is required when NTP is enabled.")
    for server in servers:
        if len(server) > 253:
            raise ValueError(f"NTP server name is too long: {server}")
        try:
            ipaddress.ip_address(server)
            continue
        except ValueError:
            pass
        if (
            not re.fullmatch(r"[A-Za-z0-9.-]+", server)
            or server.startswith(".")
            or server.endswith(".")
        ):
            raise ValueError(f"Invalid NTP server: {server}")


def run_remote(ssh: paramiko.SSHClient, command: str) -> tuple[int, str, str]:
    _, stdout, stderr = ssh.exec_command(command)
    exit_code = stdout.channel.recv_exit_status()
    return (
        exit_code,
        stdout.read().decode(errors="replace").strip(),
        stderr.read().decode(errors="replace").strip(),
    )


def discover_host(ssh: paramiko.SSHClient) -> dict[str, str]:
    commands = {
        "hostname": "hostname",
        "os": "grep '^PRETTY_NAME=' /etc/os-release | cut -d= -f2-",
        "kernel": "uname -r",
        "virsh": "virsh --version",
        "libvirt": "virsh version --daemon 2>/dev/null | grep 'Running against daemon' || true",
        "cpu": "nproc",
        "memory": "free -h | awk '/^Mem:/ {print $2 \" total, \" $7 \" available\"}'",
        "bridges": "ip -br link show type bridge | awk '{print $1}'",
        "storage": "virsh pool-list --all",
        "vms": "virsh list --all --name",
    }

    result = {}
    for key, command in commands.items():
        code, out, err = run_remote(ssh, command)
        result[key] = out if code == 0 else f"ERROR: {err or 'command failed'}"
    return result


def discover_storage_pools(ssh: paramiko.SSHClient) -> list[dict[str, str]]:
    code, out, err = run_remote(
        ssh,
        "virsh pool-list --all --name | sed '/^$/d'",
    )
    if code != 0:
        raise RuntimeError(f"Unable to list libvirt storage pools: {err}")

    pools = []
    for pool in out.splitlines():
        pool = pool.strip()
        if not pool:
            continue

        code, info, err = run_remote(ssh, f"virsh pool-info {pool!r}")
        if code != 0:
            pools.append({"name": pool, "status": "ERROR", "details": err})
            continue

        values: dict[str, str] = {"name": pool}
        for line in info.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                values[key.strip().lower()] = value.strip()
        pools.append(values)

    return pools


def find_storage_pool(
    pools: list[dict[str, str]], requested_pool: str
) -> dict[str, str] | None:
    for pool in pools:
        if pool.get("name") == requested_pool:
            return pool
    return None


def storage_available_gb(pool: dict[str, str]) -> float | None:
    available = pool.get("available")
    if not available:
        return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", available)
    if not match:
        return None

    value = float(match.group(1))
    unit = available.lower()
    if "tb" in unit:
        return value * 1024
    if "mb" in unit:
        return value / 1024
    if "kb" in unit:
        return value / (1024 * 1024)
    return value


def discover_iso_files(ssh: paramiko.SSHClient) -> list[str]:
    command = (
        f"mkdir -p {TEMP_ISO_DIR!r} && "
        f"find {TEMP_ISO_DIR!r} -maxdepth 1 -type f "
        "\( -iname '*.iso' -o -iname '*.ISO' \) "
        "-printf '%f\\n' | sort"
    )
    code, out, err = run_remote(ssh, command)
    if code != 0:
        raise RuntimeError(f"Unable to inspect ISO directory '{TEMP_ISO_DIR}': {err}")
    return [name.strip() for name in out.splitlines() if name.strip()]


def select_iso(ssh: paramiko.SSHClient, ubuntu_version: str) -> str:
    iso_files = discover_iso_files(ssh)

    if not iso_files:
        raise RuntimeError(
            f"No Ubuntu ISO found in the '{TEMP_ISO_DIR}/' directory on the KVM host. "
            "Upload an ISO there before starting the build."
        )

    if len(iso_files) == 1:
        print(f"ISO selected automatically: {TEMP_ISO_DIR}/{iso_files[0]}")
        return f"{TEMP_ISO_DIR}/{iso_files[0]}"

    print(f"\nMultiple ISO files found in '{TEMP_ISO_DIR}/':")
    for index, filename in enumerate(iso_files, 1):
        print(f"  {index}. {filename}")

    while True:
        choice = ask(f"Select ISO for Ubuntu {ubuntu_version}", "1")
        try:
            index = int(choice)
            if 1 <= index <= len(iso_files):
                selected = iso_files[index - 1]
                return f"{TEMP_ISO_DIR}/{selected}"
        except ValueError:
            pass
        print("Invalid selection.")


def run_preflight(
    ssh: paramiko.SSHClient,
    params: dict,
) -> tuple[bool, dict[str, str]]:
    print("\n=== PRE-FLIGHT CHECK ===")
    results: dict[str, str] = {}
    passed = True

    # libvirt
    code, out, err = run_remote(ssh, "command -v virsh >/dev/null && virsh --version")
    results["libvirt"] = f"OK (virsh {out})" if code == 0 else f"FAILED: {err}"
    passed &= code == 0
    print(f"  {'OK' if code == 0 else 'FAIL'}  libvirt/virsh")

    # bridge
    code, out, err = run_remote(
        ssh,
        f"ip -o link show {params['bridge']!r} type bridge >/dev/null 2>&1",
    )
    results["bridge"] = (
        f"OK ({params['bridge']})" if code == 0 else f"FAILED: bridge not found"
    )
    passed &= code == 0
    print(f"  {'OK' if code == 0 else 'FAIL'}  network bridge: {params['bridge']}")

    # VM name
    code, out, err = run_remote(
        ssh,
        f"virsh dominfo {params['vm_name']!r} >/dev/null 2>&1",
    )
    vm_free = code != 0
    results["vm_name"] = (
        "OK - name is available" if vm_free else "FAILED - VM already exists"
    )
    passed &= vm_free
    print(f"  {'OK' if vm_free else 'FAIL'}  VM name: {params['vm_name']}")

    # Storage pool
    pools = discover_storage_pools(ssh)
    pool = find_storage_pool(pools, params["storage_pool"])
    pool_ok = bool(pool and pool.get("state", "").lower() == "running")
    results["storage_pool"] = (
        f"OK - {params['storage_pool']}"
        if pool_ok
        else f"FAILED - storage pool '{params['storage_pool']}' is not active"
    )
    passed &= pool_ok
    print(f"  {'OK' if pool_ok else 'FAIL'}  storage pool: {params['storage_pool']}")

    # Storage capacity
    free_gb = storage_available_gb(pool) if pool else None
    required_gb = params["disk"] + MIN_STORAGE_RESERVE_GB
    storage_ok = free_gb is not None and free_gb >= required_gb
    if free_gb is None:
        results["storage_space"] = "FAILED - available capacity could not be determined"
    else:
        results["storage_space"] = (
            f"OK - {free_gb:.1f} GB free / {required_gb} GB required"
            if storage_ok
            else f"FAILED - {free_gb:.1f} GB free / {required_gb} GB required"
        )
    passed &= storage_ok
    print(
        f"  {'OK' if storage_ok else 'FAIL'}  storage space: "
        f"{free_gb:.1f} GB free" if free_gb is not None
        else "  FAIL  storage space: unable to determine"
    )

    # IP duplicate check - best effort on the KVM host network.
    ip_value = str(ipaddress.ip_interface(params["ip"]).ip)
    code, out, err = run_remote(
        ssh,
        f"ip -4 neigh show | awk '{{print $1}}' | grep -Fx {ip_value!r} >/dev/null",
    )
    ip_free = code != 0
    results["ip"] = (
        "OK - not found in neighbor table"
        if ip_free
        else "WARNING/FAILED - IP appears in neighbor table"
    )
    passed &= ip_free
    print(f"  {'OK' if ip_free else 'FAIL'}  IP availability: {ip_value}")

    # ISO
    try:
        iso_path = select_iso(ssh, params["ubuntu"])
        params["iso_path"] = iso_path
        code, out, err = run_remote(
            ssh,
            f"test -r {iso_path!r} && stat -c '%s' {iso_path!r}",
        )
        iso_ok = code == 0
        if iso_ok:
            size_gb = int(out) / (1024 ** 3)
            results["iso"] = f"OK - {iso_path} ({size_gb:.2f} GB)"
        else:
            results["iso"] = f"FAILED - ISO is not readable: {iso_path}"
        passed &= iso_ok
        print(f"  {'OK' if iso_ok else 'FAIL'}  Ubuntu ISO: {iso_path}")
    except RuntimeError as exc:
        results["iso"] = f"FAILED - {exc}"
        passed = False
        print(f"  FAIL  Ubuntu ISO: {exc}")

    print(
        f"\nPRE-FLIGHT: {'PASSED' if passed else 'FAILED'}"
    )
    return passed, results


def connect(
    host: str,
    username: str,
    key_file: str | None,
    password: str | None,
) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    kwargs = {
        "hostname": host,
        "username": username,
        "timeout": 10,
        "banner_timeout": 10,
        "auth_timeout": 10,
    }

    if key_file:
        kwargs["key_filename"] = key_file
    elif password:
        kwargs["password"] = password
    else:
        kwargs["look_for_keys"] = True
        kwargs["allow_agent"] = True

    client.connect(**kwargs)
    return client


def collect_parameters() -> dict:
    print("\n=== KVM Ubuntu VM Builder ===\n")

    return {
        "kvm_host": ask("KVM host IP/FQDN"),
        "kvm_user": ask("KVM SSH username", "root"),
        "ssh_key": ask("SSH private key path", "~/.ssh/id_ed25519"),
        "vm_name": ask("VM name"),
        "hostname": ask("VM hostname"),
        "ip": ask("IP address/prefix, e.g. 10.10.20.51/24"),
        "gateway": ask("Gateway"),
        "dns": ask("DNS servers, comma separated", "1.1.1.1"),
        "bridge": ask("Network bridge", "br851"),
        "storage_pool": ask("Libvirt storage pool", "default"),
        "cpu": ask_int("CPU count", 2),
        "memory": ask_int("RAM GB", 4),
        "disk": ask_int("Disk GB", 20),
        "ubuntu": ask("Ubuntu version", "24.04"),
        "user": ask("Ubuntu SSH username", "admin"),
        "timezone": ask("Timezone", "Europe/Prague"),
        "ntp_enabled": ask("Enable NTP time synchronization? (yes/no)", "yes").lower()
        in {"yes", "y"},
        "ntp_servers": ask(
            "NTP servers, comma separated",
            "pool.ntp.org",
        ),
        "ssh_password_auth": ask(
            "Allow SSH password authentication? (yes/no)",
            "no",
        ).lower()
        in {"yes", "y"},
    }


def validate_parameters(p: dict) -> list[str]:
    errors = []

    try:
        validate_vm_name(p["vm_name"])
    except ValueError as exc:
        errors.append(str(exc))

    try:
        validate_hostname(p["hostname"])
    except ValueError as exc:
        errors.append(str(exc))

    try:
        validate_ip(p["ip"])
    except ValueError as exc:
        errors.append(str(exc))

    try:
        validate_ip_address(p["gateway"], "gateway")
    except ValueError as exc:
        errors.append(str(exc))

    try:
        validate_dns_servers(p["dns"])
    except ValueError as exc:
        errors.append(str(exc))

    if p["ntp_enabled"]:
        try:
            validate_ntp_servers(p["ntp_servers"])
        except ValueError as exc:
            errors.append(str(exc))

    if not p["bridge"]:
        errors.append("Bridge cannot be empty.")
    if not p["storage_pool"]:
        errors.append("Storage pool cannot be empty.")
    if p["cpu"] < 1:
        errors.append("CPU count must be >= 1.")
    if p["memory"] < 1:
        errors.append("RAM must be >= 1 GB.")
    if p["disk"] < 5:
        errors.append("Disk must be >= 5 GB.")
    if not p["user"]:
        errors.append("Ubuntu username cannot be empty.")
    if not p["timezone"]:
        errors.append("Timezone cannot be empty.")
    if p["ubuntu"] not in {"24.04"}:
        errors.append("Currently supported Ubuntu version is 24.04.")

    return errors


def print_plan(p: dict) -> None:
    print("\n=== BUILD PLAN ===")
    for key, value in p.items():
        if key not in {"ssh_key"}:
            print(f"{key:18}: {value}")

    print("\nPlanned actions:")
    actions = [
        "Connect to KVM host via SSH",
        "Run pre-flight checks",
        "Validate libvirt/virsh",
        "Validate network bridge",
        "Validate storage pool and free capacity",
        "Check VM name and IP availability",
        "Find Ubuntu ISO in temp/ and select it if multiple are present",
        "Verify ISO is readable",
        "Create VM directory and qcow2 disk",
        "Generate Ubuntu autoinstall/cloud-init configuration",
        "Configure hostname and static networking",
        "Configure timezone",
        "Configure NTP time synchronization",
        "Configure SSH and initial administrator",
        "Configure serial console: console=ttyS0,115200n8",
        "Enable serial-getty@ttyS0.service",
        "Create and start Ubuntu VM",
        "Wait for network and SSH",
        "Verify time synchronization with timedatectl",
        "Run post-install validation",
    ]
    for number, action in enumerate(actions, 1):
        print(f"  {number:2}. {action}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build Ubuntu Server VMs on KVM/libvirt."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the planned build without changing the KVM host.",
    )
    args = parser.parse_args()

    try:
        params = collect_parameters()
        errors = validate_parameters(params)

        if errors:
            print("\nValidation failed:")
            for error in errors:
                print(f"  - {error}")
            return 1

        print_plan(params)

        if args.dry_run:
            print("\nDRY RUN: no changes will be made.")
            print(
                f"ISO source: {TEMP_ISO_DIR}/ on the KVM host "
                "(ISO selection is performed during connected pre-flight)."
            )
            return 0

        print("\nConnecting to KVM host...")
        password = None
        if not params["ssh_key"]:
            password = getpass.getpass("KVM SSH password: ")

        key_file = params["ssh_key"] or None
        if key_file:
            key_file = os.path.expanduser(key_file)

        ssh = None
        try:
            ssh = connect(
                params["kvm_host"],
                params["kvm_user"],
                key_file,
                password,
            )
            print("SSH connection: OK")

            host_info = discover_host(ssh)
            print("\n=== KVM HOST DISCOVERY ===")
            for key, value in host_info.items():
                print(f"{key:10}: {value}")

            preflight_ok, _ = run_preflight(ssh, params)
            if not preflight_ok:
                print("\nBuild stopped. Fix the pre-flight errors before creating the VM.")
                return 1

            print("\nPhase 1 completed.")
            print("No VM was created in this version.")
            print("All validated parameters are ready for the Phase 2 VM creation workflow.")
            return 0
        finally:
            if ssh:
                ssh.close()

    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    except (paramiko.SSHException, OSError) as exc:
        print(f"\nConnection/system error: {exc}")
        return 2
    except Exception as exc:
        print(f"\nError: {exc}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
