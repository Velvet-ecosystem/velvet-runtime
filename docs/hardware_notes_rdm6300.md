# RDM6300 Founder Hardware Notes

- Reader: RDM6300, 125 kHz, 9600-baud TTL UART output.
- Intended tag: writable T5577/EM4305-class ring.
- Supply the reader from regulated 5 V.
- Connect grounds.
- Level-shift reader TX down to the UP Squared 3.3 V UART RX.
- Leave reader RX disconnected.
- Default Linux device is `/dev/ttyS5`; verify the installed board and kernel before enabling the service.
- The writable ring is cloneable static evidence and is never sufficient by itself for authority or owner-presence decisions.
