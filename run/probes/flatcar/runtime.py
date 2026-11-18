"""Read acceleration and vCPU progress from one active libvirt domain."""
import re
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET


class Unproven(ValueError):
    """A safe diagnostic code, without hypervisor output."""


def live_domain(xml, name, vmi_uid):
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
    # KubeVirt versions can store runtime metadata outside the domain XML.
    owner_uids = root.findall("./metadata/{http://kubevirt.io}kubevirt/{http://kubevirt.io}uid")
    if owner_uids and (len(owner_uids) != 1 or owner_uids[0].text != vmi_uid):
        raise Unproven("vmi_uid_mismatch")
    if root.find("{http://libvirt.org/schemas/domain/qemu/1.0}commandline") is not None:
        raise Unproven("custom_emulator_arguments")
    return domain_uuid, ident


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


def measure(read, name, vmi_uid, wait=time.sleep):
    expected = live_domain(read("dumpxml", name), name, vmi_uid)
    domain_uuid, _ = expected

    def sample():
        return vcpu_time(read("domstats", "--state", "--vcpu", domain_uuid))

    first = sample()
    for _ in range(5):
        wait(2)
        current = sample()
        if live_domain(read("dumpxml", name), name, vmi_uid) != expected:
            raise Unproven("domain_identity_changed")
        if current < first:
            raise Unproven("vcpu_time_regressed")
        if current > first:
            return current - first
    raise Unproven("vcpu_time_unchanged")


def virsh(command, operation, *args):
    try:
        result = subprocess.run([*command, "virsh", "--readonly", operation, *args],
                                capture_output=True, timeout=15, check=False)
    except subprocess.TimeoutExpired:
        raise Unproven(f"readonly_{operation}_timeout") from None
    except OSError:
        raise Unproven(f"readonly_{operation}_unavailable") from None
    if result.returncode:
        error = result.stderr.lower()
        denied = any(word in error for word in (b"denied", b"forbidden", b"not authorized"))
        reason = "denied" if denied else "failed"
        raise Unproven(f"readonly_{operation}_{reason}")
    return result.stdout


if __name__ == "__main__":
    from functools import partial

    domain_name, guest_uid, *command = sys.argv[1:]
    try:
        delta = measure(partial(virsh, command), domain_name, guest_uid)
        print(f"kvm_vcpu=proven vcpu0_delta_ns={delta}")
    except Unproven as exc:
        print(f"kvm_vcpu=unproven vcpu_reason={exc}")
