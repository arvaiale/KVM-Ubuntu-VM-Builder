# KVM Ubuntu VM Builder

Automation project for building and configuring Ubuntu Server virtual machines on KVM/libvirt hosts.

## Project goal

The goal is to automate the complete Ubuntu Server VM provisioning workflow so that an administrator provides the required VM parameters once and the tool performs the remaining work automatically.

The initial target environment is:

- KVM
- libvirt / virsh
- Ubuntu Server 24.04
- SSH access to the KVM host
- Linux bridge networking
- qcow2 VM disks
- cloud-init / Ubuntu autoinstall
- serial console access
- automatic timezone and NTP configuration

## Planned workflow

1. Ask the administrator for VM parameters.
2. Validate all supplied values.
3. Connect to the selected KVM host over SSH.
4. Verify KVM/libvirt availability.
5. Verify the requested network bridge.
6. Verify storage availability and capacity.
7. Check that the VM name and IP address are not already in use.
8. Create the VM storage.
9. Generate the Ubuntu installation configuration.
10. Create the VM definition.
11. Install Ubuntu Server automatically.
12. Configure hostname, networking, DNS, SSH and initial user.
13. Configure timezone.
14. Configure NTP time synchronization.
15. Configure serial console access.
16. Start the VM.
17. Wait for the operating system and network to become available.
18. Test SSH connectivity.
19. Verify time synchronization.
20. Run post-installation validation.
21. Produce a clear success/failure report.
22. Optionally clean up partially created resources after a failed build.

## Parameters

The interactive builder is designed to collect:

- KVM host IP/FQDN
- KVM SSH username
- SSH private key
- VM name
- hostname
- IPv4 address/prefix
- gateway
- DNS servers
- Ubuntu version
- CPU count
- RAM
- disk size
- libvirt storage pool/location
- network bridge
- Ubuntu SSH username
- timezone
- NTP enabled/disabled
- one or more NTP servers
- SSH password authentication policy
- serial console settings

Sensitive information such as passwords and private SSH keys must never be stored in the repository.

## Time synchronization

Ubuntu VMs will be configured with an explicit timezone and NTP settings during automated installation/post-installation.

Default timezone:

```text
Europe/Prague
```

NTP can use either internal company NTP servers or public servers such as:

```text
pool.ntp.org
```

Multiple servers are supported, for example:

```text
10.10.10.10,10.10.10.11
```

After installation the builder should verify synchronization and report it separately from the VM installation result. A VM can therefore complete successfully with an NTP warning instead of being incorrectly reported as a total installation failure.

Expected validation includes:

```bash
timedatectl status
timedatectl show-timesync --all
```

## SSH and security

The preferred access method is SSH public-key authentication.

The planned default is:

- create an administrator user
- install the supplied SSH public key
- disable SSH password authentication unless explicitly enabled
- do not require root SSH login
- verify TCP/22 after installation

## Serial console

The VM will be configured for a usable libvirt serial console.

The Ubuntu kernel configuration will include:

```text
console=ttyS0,115200n8
```

The guest will enable:

```bash
systemctl enable serial-getty@ttyS0.service
```

The intended administrator workflow is:

```bash
virsh console <vm-name>
```

This provides a recovery path when SSH or the network is unavailable.

## Target architecture

```
KVM-Ubuntu-VM-Builder
│
├── README.md
├── requirements.txt
├── .gitignore
├── config/
│   └── example.yaml
├── src/
│   └── kvm_vm_builder/
│       ├── main.py
│       ├── config.py
│       ├── validators.py
│       ├── ssh.py
│       ├── kvm.py
│       ├── storage.py
│       ├── network.py
│       ├── cloud_init.py
│       ├── installer.py
│       ├── post_install.py
│       └── logger.py
├── templates/
│   ├── cloud-init/
│   └── autoinstall/
└── tests/
```

## Development phases

### Phase 1 - Discovery and validation

Build a read-only discovery mode.

The tool connects to a KVM host and reports:

- hostname
- OS
- kernel
- libvirt/virsh version
- available bridges
- available storage pools
- host CPU and memory
- existing VMs

The interactive parameters are also validated, including network, hostname, timezone, NTP and SSH policy.

**No VM changes are made in Phase 1.**

### Phase 2 - VM definition

Implement VM creation using libvirt/virsh.

Tasks:

- create VM directory
- create qcow2 disk
- configure CPU
- configure RAM
- configure network
- configure serial console
- generate libvirt XML or use virt-install

### Phase 3 - Automated Ubuntu installation

Implement unattended Ubuntu Server installation.

Preferred approach:

- Ubuntu autoinstall
- cloud-init
- no interactive installer
- static or DHCP networking
- SSH enabled automatically
- timezone configured automatically
- NTP configured automatically
- serial console available automatically

### Phase 4 - Post-install configuration

After installation:

- wait for the VM
- detect network availability
- test TCP/22
- connect using SSH
- verify hostname
- verify IP
- verify disk
- verify RAM
- verify CPU
- verify timezone
- verify NTP synchronization
- verify serial-getty
- optionally install requested packages

### Phase 5 - Safety and rollback

Before creating the VM:

- validate VM name
- validate IP address
- validate subnet
- validate gateway
- validate DNS
- validate bridge
- validate disk size
- validate available storage
- validate requested RAM/CPU
- check for duplicate VM
- check for duplicate IP where possible

If a build fails, the tool should provide a clear error and optionally clean up partially created resources.

Example:

```text
BUILD FAILED

VM installation:       FAILED
Network:               OK
SSH:                   NOT TESTED
Serial console:        OK
NTP:                   NOT TESTED

Remove incomplete VM and disk? [Y/n]
```

### Phase 6 - CLI

Example future commands:

```bash
python3 -m kvm_vm_builder create
python3 -m kvm_vm_builder validate
python3 -m kvm_vm_builder discover
python3 -m kvm_vm_builder list
python3 -m kvm_vm_builder delete ubuntu-test01
```

### Phase 7 - Configuration files

Support both interactive mode and configuration files.

Example:

```yaml
vm:
  name: ubuntu-test01
  hostname: ubuntu-test01
  cpu: 4
  memory_gb: 8
  disk_gb: 50

network:
  bridge: br851
  address: 10.10.20.51/24
  gateway: 10.10.20.1
  dns:
    - 10.10.20.10
    - 1.1.1.1

ubuntu:
  version: "24.04"
  timezone: Europe/Prague
  ntp:
    enabled: true
    servers:
      - 10.10.10.10
      - 10.10.10.11

access:
  username: admin
  ssh_public_key: ~/.ssh/id_ed25519.pub
  password_authentication: false

console:
  serial:
    enabled: true
    device: ttyS0
    baud: 115200
```

Secrets must be supplied through environment variables, SSH agent, or another secure mechanism.

## Design principles

- Safe by default
- No destructive action without explicit confirmation
- Idempotent where practical
- Clear logging
- Dry-run mode before changes
- SSH key authentication preferred
- Password authentication disabled by default
- No secrets committed to Git
- Serial console enabled by default
- Explicit timezone and NTP configuration
- Post-install validation
- Modular Python implementation
- Easy to extend to additional Linux distributions later

## Future possibilities

The project may later support:

- Debian
- Rocky Linux / AlmaLinux
- VM cloning
- VM deletion
- VM rebuild
- VM inventory
- CloudStack API
- multiple KVM hosts
- automatic KVM host selection
- templates
- Ansible integration
- GitHub Actions for validation/testing

## Current status

**Phase 1 - Discovery and validation**

The project currently provides an interactive, read-only builder prototype with dry-run support. It validates VM, network, timezone, NTP and SSH parameters and displays the planned provisioning workflow.

No VM creation functionality is implemented yet.
