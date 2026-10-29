#!/bin/sh
# Runs the package tests. With Xcode installed, plain `swift test` works.
# With only the Command Line Tools, the default Swift Build system loses the
# Swift Testing macro plugin intermittently, so use the native build system
# and point it at the Testing framework explicitly.
set -e
cd "$(dirname "$0")"
if xcode-select -p | grep -q CommandLineTools; then
    CLT=/Library/Developer/CommandLineTools
    exec swift test --build-system native \
        -Xswiftc -F -Xswiftc "$CLT/Library/Developer/Frameworks" \
        -Xswiftc -plugin-path -Xswiftc "$CLT/usr/lib/swift/host/plugins/testing" \
        -Xlinker -F -Xlinker "$CLT/Library/Developer/Frameworks" \
        -Xlinker -rpath -Xlinker "$CLT/Library/Developer/Frameworks" \
        "$@"
fi
exec swift test "$@"
