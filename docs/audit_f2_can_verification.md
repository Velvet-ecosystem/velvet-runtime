# Central passive CAN verification

Runtime delegates its legacy body-state verification wrapper to vehicle-CAN.
Every physical reader, including both direct Runtime observation factories, must
pass the canonical kernel guard in that package before backend construction.
No Runtime parser accepts configuration syntax as diagnostic evidence.

Dependency: velvet-vehicle-can commit ebdd8740d85939e4de0087870b4e31c240ac9348.
The two full-suite workflows install that exact source for integration testing.
Merge/deploy vehicle-CAN first, then this adapter. Old packages that cannot prove
passive mode must not be used for physical commissioning. No hardware/actuation
was enabled; isolated bench and target iproute2 JSON acceptance remain pending.
