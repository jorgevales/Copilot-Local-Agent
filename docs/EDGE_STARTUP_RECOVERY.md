# Edge native-crash and launch recovery — 14 October 2026

The reported `python.exe` dialog describes invalid memory access. Its addresses
alone do not identify the crashing module or establish exhausted RAM or disk
space. See Microsoft's [access-violation explanation](https://learn.microsoft.com/en-us/shows/inside/access-violation-c0000005-read-or-write).
The exact fault in the company VDI has not been reproduced on this workstation.

The inspected ownership code contained an unsafe native string read:
`UNICODE_STRING.Buffer` used an automatically dereferenced `LPWSTR`, followed by
another pointer read without verifying the returned allocation. A focused test
failed at this call before the change. The replacement reads a pointer-sized
integer, validates byte lengths and allocation bounds, then decodes a slice of
the owned buffer as UTF-16. It does not assume a trailing terminator.
This follows the [documented UNICODE_STRING lengths](https://learn.microsoft.com/en-us/windows/win32/api/ntdef/ns-ntdef-_unicode_string).

Windows process and TCP ownership queries now run in an isolated, five-second
Python helper. If a native DLL or helper fails, the parent remains available and
uses independent fallbacks:

- Process identity: isolated native query, then PowerShell CIM, then WMI.
- Listener identity: isolated native TCP table, then Get-NetTCPConnection,
  then numeric netstat output. Ambiguous or unverifiable ownership is rejected.

The IPv6 TCP row layout and native function argument types were also corrected
against [Microsoft's TCP6 owner-PID structure](https://learn.microsoft.com/en-us/windows/win32/api/tcpmib/ns-tcpmib-mib_tcp6row_owner_pid).
The helper and detached Python browser owner disable blocking crash dialogs in
their own processes so a failed child can exit and recovery can continue.

Normal visible Edge startup keeps its existing Playwright-owner route first.
For a new owned session that cannot open or attach its endpoint, recovery tries
installed Edge directly without the second Python/Playwright owner, the verified
extended Windows profile spelling, the verified S: spelling where available,
and direct Edge with software graphics. Every route retains the chosen port and
the exact existing profile. Profiles are not moved, erased or copied to C:.

Direct launches probe actual profile mkdir/write/flush/readback. Folder access
errors are not inferred from free-space metadata or labelled insufficient RAM.
S:/UNC identity checks and existing shared temporary-directory fallbacks remain
active. A same-file identity shortcut requires meaningful nonzero file IDs;
redirectors with absent IDs still require exact profile spelling proof.

An owned launch gets a 15-second limit for a *missing* endpoint before recovery;
each direct retry waits at most ten seconds for a missing endpoint. A responding
endpoint still receives the browser-handshake budget. There is no infinite launch
loop. Existing-session attachment and exact live-proof port/profile bindings keep
their dedicated checks. Corporate debugging policy, occupied ports and unrelated
profiles are never bypassed. Sign-in and MFA remain manual.

Validation: 118 focused startup, ownership, browser, port-selection and session
tests passed. Coverage includes the unsafe-read regression, malformed native
pointers/lengths, bounded Unicode without a terminator, simulated native exits,
CIM/WMI/netstat fallbacks, real IPv4/IPv6 listener ownership, and recovery of a
new session after a simulated `0xC0000005` Python-owner exit. An installed Edge
was launched directly with an isolated profile and verified CDP ownership;
headless operation was used only for this `about:blank` test fixture. Production
launches remain visible. The exact VDI crash, live S: storage and redirected UNC
browser launch still require validation in the target environment.
