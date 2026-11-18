"""The host trial admits only observations of its original live domain."""
import runpy
from pathlib import Path

import pytest

runtime = runpy.run_path(str(Path(__file__).resolve().parents[1] / "probes/flatcar/runtime.py"))
measure = runtime["measure"]
Unproven = runtime["Unproven"]
NAME = "default_host-probe"
OWNER = "00000000-0000-4000-8000-000000000001"
DOMAIN = "00000000-0000-4000-8000-000000000002"
FIRMWARE = "00000000-0000-4000-8000-000000000003"
OWNER_ENTRY = f"<uid>{OWNER}</uid>"
FIRMWARE_ENTRY = f"<entry name='uuid'>{FIRMWARE}</entry>"
XML = (f"<domain type='kvm' id='12'><name>{NAME}</name><uuid>{DOMAIN}</uuid>"
       f"<sysinfo type='smbios'><system>{FIRMWARE_ENTRY}</system></sysinfo>"
       f"<metadata><kubevirt xmlns='http://kubevirt.io'>{OWNER_ENTRY}</kubevirt></metadata></domain>")
MONITOR = b"/usr/bin/virt-launcher-monitor\0--name\0host-probe\0--uid\0" + OWNER.encode("ascii") + b"\0"
STATS = b"state.state=1\nvcpu.current=1\nvcpu.0.state=2\nvcpu.0.time=100\n"


def reading(xml=XML, last_xml=None, stats=STATS, last_stats=None):
    """Require the production reader to scope every query to the expected name or UUID."""
    xml_calls = 0
    stat_calls = 0

    def read(operation, *args):
        nonlocal xml_calls, stat_calls
        if operation == "dumpxml":
            assert args == (NAME,)
            xml_calls += 1
            return xml if xml_calls == 1 or last_xml is None else last_xml
        assert (operation, *args) == ("domstats", "--raw", "--state", "--vcpu", DOMAIN)
        stat_calls += 1
        return stats if stat_calls == 1 or last_stats is None else last_stats
    return read


@pytest.mark.parametrize("uid_entry,field", [(OWNER_ENTRY, "matched"), ("<uid/>", "empty"), ("", "absent")])
def test_live_kvm_with_vcpu_progress(uid_entry, field):
    read = reading(xml=XML.replace(OWNER_ENTRY, uid_entry), last_stats=STATS.replace(b"100", b"116"))
    observations = []

    def observe(operation, *args):
        observations.append(operation)
        return read(operation, *args)

    def read_monitor():
        observations.append("monitor")
        return MONITOR

    assert measure(observe, read_monitor, NAME, OWNER, FIRMWARE, lambda _: None) == (16, field)
    assert observations == ["monitor", "dumpxml", "domstats", "domstats", "dumpxml", "monitor"]


@pytest.mark.parametrize("read,reason", [
    (reading(xml=XML.replace("'kvm'", "'qemu'")), "domain_type_not_kvm"),
    (reading(xml=XML.replace(" id='12'", "")), "inactive_domain"),
    (reading(xml=XML.replace(NAME, "other")), "domain_name_mismatch"),
    (reading(xml=XML.replace(OWNER, DOMAIN)), "vmi_uid_mismatch"),
    (reading(xml=XML.replace(OWNER_ENTRY, OWNER_ENTRY + "<uid/>")), "vmi_uid_mismatch"),
    (reading(xml=XML.replace(FIRMWARE, DOMAIN)), "domain_firmware_uuid_mismatch"),
    (reading(xml=XML.replace(FIRMWARE_ENTRY, "")), "domain_firmware_uuid_mismatch"),
    (reading(last_xml=XML.replace(FIRMWARE_ENTRY, FIRMWARE_ENTRY * 2)), "domain_firmware_uuid_mismatch"),
    (reading(xml=XML.replace("</domain>", "<commandline xmlns='http://libvirt.org/schemas/domain/qemu/1.0'/></domain>")),
     "custom_emulator_arguments"),
    (reading(last_xml=XML.replace("id='12'", "id='13'")), "domain_identity_changed"),
    (reading(last_xml=XML.replace(DOMAIN, OWNER)), "domain_identity_changed"),
    (reading(stats=STATS.replace(b"state.state=1", b"state.state=3")), "domain_not_running"),
    (reading(stats=STATS.replace(b"vcpu.0.state=2", b"vcpu.0.state=0")), "vcpu_not_online"),
    (reading(stats=STATS.replace(b"vcpu.0.time=100", b"cpu.time=100")), "vcpu_time_missing"),
    (reading(last_stats=STATS.replace(b"100", b"99")), "vcpu_time_regressed"),
    (reading(), "vcpu_time_unchanged"),
])
def test_insufficient_evidence(read, reason):
    with pytest.raises(Unproven, match=f"^{reason}$"):
        measure(read, lambda: MONITOR, NAME, OWNER, FIRMWARE, lambda _: None)


@pytest.mark.parametrize("monitor_samples", [
    [MONITOR.replace(OWNER.encode("ascii"), DOMAIN.encode("ascii"))],
    [MONITOR, b"/pause\0--uid\0" + OWNER.encode("ascii") + b"\0"],
    [MONITOR, MONITOR + b"--uid=" + OWNER.encode("ascii") + b"\0"],
])
def test_live_kvm_cannot_prove_progress_with_a_different_launcher_uid(monitor_samples):
    read = reading(xml=XML.replace(OWNER_ENTRY, "<uid/>"), last_stats=STATS.replace(b"100", b"116"))
    with pytest.raises(Unproven, match="^launcher_vmi_uid_mismatch$"):
        measure(read, iter(monitor_samples).__next__, NAME, OWNER, FIRMWARE, lambda _: None)


def test_rejected_read_only_connection_has_no_fallback(monkeypatch):
    import subprocess

    calls = []

    def denied(argv, **options):
        calls.append(argv)
        assert options["capture_output"] and options["timeout"] > 0
        return subprocess.CompletedProcess(argv, 1, b"", b"permission denied: private detail")

    monkeypatch.setattr(subprocess, "run", denied)
    with pytest.raises(Unproven, match="^readonly_dumpxml_denied$"):
        runtime["virsh"](["launcher"], "dumpxml", NAME)
    assert calls == [["launcher", "virsh", "--readonly", "dumpxml", NAME]]
