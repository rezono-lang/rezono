# virt-tail emits complete serial lines. Consume every line without echoing it.
{ sub(/\r+$/, "") }
$0 == expected { matches++ }
END { print NR, matches + 0 }
