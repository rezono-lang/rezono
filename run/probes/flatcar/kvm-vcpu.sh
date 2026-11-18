# Run inside the identified launcher's compute container.
export LC_ALL=C
for proc in /proc/[0-9]*; do
    exe=$(readlink "$proc/exe") || continue
    case "$exe" in
        /usr/bin/qemu-system-x86_64|/usr/libexec/qemu-kvm|/usr/bin/qemu-kvm) ;;
        *) continue ;;
    esac
    for fd in "$proc"/fd/*; do
        target=$(readlink "$fd") || continue
        case "$target" in
            anon_inode:kvm-vcpu:*) index=${target#anon_inode:kvm-vcpu:} ;;
            *) continue ;;
        esac
        case "$index" in
            ''|*[!0-9]*) continue ;;
            *) exit 0 ;;
        esac
    done
done
exit 1
