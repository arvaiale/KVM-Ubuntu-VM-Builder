# KVM Ubuntu VM Builder

Automation project for building and configuring Ubuntu Server virtual machines on KVM/libvirt hosts.

## Project goal

The goal is to automate the complete Ubuntu Server VM provisioning workflow so that an administrator provides the required VM parameters once and the tool performs the remaining work automatically.

The initial target environment is:

- KVM
- libvirt / virsh
- Ubuntu Server
- SSH access to the KVM host
- Linux bridge networking
- qcow2 VM disks
- cloud-init / Ubuntu autoinstall

## Planned workflow

1. Ask the administrator for VM parameters.
2. Validate all supplied values.
3. Connect to the selected KVM host over SSH.
4. Verify KVM/libvirt availability.
5. Verify the requested network bridge.
6. Verify storage availability.
7. Check that the VM name and IP address are not already in use.
8. Create the VM storage.
9. Generate the Ubuntu installation configuration.
10. Create the VM definition.
11. Install Ubuntu Server automatically.
12. Configure hostname, networking, SSH and initial user.
13. Start the VM.
14. Wait for the operating system to become available.
15. Test network connectivity.
16. Test SSH connectivity.
17. Run post-installation validation.
18. Produce a clear success/failure report.

## Example input

The first interactive version should collect approximately:

- KVM host IP/FQDN
- KVM SSH username
- VM name
- hostname
- IPv4 address
- subnet/prefix
- gateway
- DNS servers
- Ubuntu version
- CPU count
- RAM
- disk size
- libvirt storage location
- network bridge
- SSH username
- SSH public key
- optional additional packages

Sensitive information such as passwords and private SSH keys must never be stored in the repository.

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

The tool should connect to a KVM host and report:

- hostname
- OS
- libvirt version
- virsh version
- available bridges
- available storage pools
- available disk space
- existing VMs
- existing VM names
- basic host capacity

No changes should be made to the host.

### Phase 2 - VM definition

Implement VM creation using libvirt/virsh.

Tasks:

- create VM directory
- create qcow2 disk
- configure CPU
- configure RAM
- configure network
- configure console
- generate libvirt XML or use virt-install

### Phase 3 - Automated Ubuntu installation

Implement unattended Ubuntu Server installation.

Preferred approach:

- cloud-init
- Ubuntu autoinstall
- No interactive installer
- Static or DHCP networking
- SSH enabled automatically

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
- optionally install requested packages

### Phase 5 - Safety and rollback

Before creating the VM:

- validate VM name
- validate IP address
- validate subnet
- validate gateway
- validate bridge
- validate disk size
- validate available storage
- validate requested RAM/CPU
- check for duplicate VM
- check for duplicate IP where possible

If a build fails, the tool should provide a clear error and optionally clean up partially created resources.

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

access:
  username: admin
  ssh_public_key: ~/.ssh/id_ed25519.pub
```

Secrets must be supplied through environment variables, SSH agent, or another secure mechanism.

## Design principles

- Safe by default
- No destructive action without explicit confirmation
- Idempotent where practical
- Clear logging
- Dry-run mode before changes
- SSH key authentication preferred
- No secrets committed to Git
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

**Project initialized - design phase**

No VM creation functionality is implemented yet.
