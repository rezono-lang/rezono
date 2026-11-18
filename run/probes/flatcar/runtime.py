"""Read acceleration and vCPU progress from one active libvirt domain."""
import re
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET


class Unproven(ValueError):
    """A safe diagnostic code, without hypervisor output."""


def verify_launcher_uid(cmdline, vmi_uid):
    args = cmdline.split(b"\0")
    uid_flags = [args[index:index + 2] for index, arg in enumerate(args[1:], 1)
                 if arg.split(b"=", 1)[0] == b"--uid"]
    if (args[0] != b"/usr/bin/virt-launcher-monitor"
            or uid_flags != [[b"--uid", vmi_uid.encode("ascii")]]):
        raise Unproven("launcher_vmi_uid_mismatch")


def live_domain(xml, name, vmi_uid, firmware_uuid):
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise Unproven("invalid_domain_xml") from None
    if root.tag != "domain" or root.findtext("name") != name:
        raise Unproven("domain_name_mismatch")
    if root.get("type") != "kvm":
        raise Unproven("domain_type_not_kvm")
    ident = root.get("id", "")
    if not re.fullmatch(r"[1-9][0-9]*", ident):
        raise Unproven("inactive_domain")
    try:
        domain_uuid = str(uuid.UUID(root.findtext("uuid", "")))
    except ValueError:
        raise Unproven("invalid_domain_uuid") from None
    # KubeVirt v1.9.1 stores the VMI UID in the launcher's metadata cache.
    owner_uids = root.findall("./metadata/{http://kubevirt.io}kubevirt/{http://kubevirt.io}uid")
    if len(owner_uids) > 1 or any(len(owner) or owner.text not in (None, vmi_uid) for owner in owner_uids):
        raise Unproven("vmi_uid_mismatch")
    firmware = root.findall("./sysinfo[@type='smbios']/system/entry[@name='uuid']")
    if len(firmware) != 1 or len(firmware[0]) or firmware[0].text != firmware_uuid:
        raise Unproven("domain_firmware_uuid_mismatch")
    if root.find("{http://libvirt.org/schemas/domain/qemu/1.0}commandline") is not None:
        raise Unproven("custom_emulator_arguments")
    if not owner_uids:
        uid_field = "absent"
    elif owner_uids[0].text is None:
        uid_field = "empty"
    else:
        uid_field = "matched"
    return domain_uuid, ident, uid_field


def vcpu_time(report):
    fields = {}
    for line in report.decode("ascii", errors="replace").splitlines():
        key, _, value = line.strip().partition("=")
        if key in {"state.state", "vcpu.current", "vcpu.0.state", "vcpu.0.time"}:
            if key in fields or not re.fullmatch(r"[0-9]+", value):
                raise Unproven("invalid_vcpu_stats")
            fields[key] = int(value)
    if fields.get("state.state") != 1:
        raise Unproven("domain_not_running")
    if fields.get("vcpu.current", 0) < 1 or fields.get("vcpu.0.state") not in (1, 2):
        raise Unproven("vcpu_not_online")
    if "vcpu.0.time" not in fields:
        raise Unproven("vcpu_time_missing")
    return fields["vcpu.0.time"]


def measure(read, read_monitor, name, vmi_uid, firmware_uuid, wait=time.sleep):
    verify_launcher_uid(read_monitor(), vmi_uid)
    expected = live_domain(read("dumpxml", name), name, vmi_uid, firmware_uuid)
    domain_uuid, _, uid_field = expected

    def sample():
        return vcpu_time(read("domstats", "--raw", "--state", "--vcpu", domain_uuid))

    first = sample()
    for _ in range(5):
        wait(2)
        current = sample()
        if live_domain(read("dumpxml", name), name, vmi_uid, firmware_uuid) != expected:
            raise Unproven("domain_identity_changed")
        verify_launcher_uid(read_monitor(), vmi_uid)
        if current < first:
            raise Unproven("vcpu_time_regressed")
        if current > first:
            return current - first, uid_field
    raise Unproven("vcpu_time_unchanged")


def checked_command(operation, args):
    try:
        result = subprocess.run(args, capture_output=True, timeout=15, check=False)
    except subprocess.TimeoutExpired:
        raise Unproven(f"{operation}_timeout") from None
    except OSError:
        raise Unproven(f"{operation}_unavailable") from None
    if result.returncode:
        error = result.stderr.lower()
        denied = any(word in error for word in (b"denied", b"forbidden", b"not authorized"))
        reason = "denied" if denied else "failed"
        raise Unproven(f"{operation}_{reason}")
    return result.stdout


def virsh(command, operation, *args):
    return checked_command(f"readonly_{operation}", [*command, "virsh", "--readonly", operation, *args])


if __name__ == "__main__":
    from functools import partial

    domain_name, guest_uid, firmware_uuid, *command = sys.argv[1:]
    read_monitor = partial(checked_command, "launcher_process", [*command, "cat", "/proc/1/cmdline"])
    try:
        delta, uid_field = measure(partial(virsh, command), read_monitor, domain_name, guest_uid, firmware_uuid)
        print(f"kvm_vcpu=proven vcpu0_delta_ns={delta} monitor_vmi_uid=matched "
              f"domain_firmware_uuid=matched xml_vmi_uid={uid_field}")
    except Unproven as exc:
        print(f"kvm_vcpu=unproven vcpu_reason={exc}")
