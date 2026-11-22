"""In-memory temporal multigraph engine using NetworkX.

Constructs sliding-window multigraph G_t = (V, E_t) and calculates:
- Pass-Through Velocity (V_p) with exponential half-life decay.
- Recipient Distribution Entropy (H_entropy) for fan-out detection.
- Multi-hop path aggregation across participating institutions.
"""
