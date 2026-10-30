# FairFlow M2 Scenario A Report: scenario_a_baselines

- **Run ID**: `smoke_20261026_151016`
- **Mode**: `smoke`
- **Timestamp UTC**: `2026-10-26T15:13:07.516865+00:00`
- **Kernel**: `Linux 6.8 (Ubuntu 24.04 aarch64)`
- **TCP Congestion Control**: `cubic`
- **Contract SHA256**: `04893b27e604b38cd0fb0e6267b307d2f05447fcde333fd73f1743b9d5a499a8`

## 1. Primary & Secondary Metrics Summary

| Arm | Valid Trials | Target Met (k/N) | Added Delay p99 Median (ms) | Added Delay p99 IQR (ms) | 95% Bootstrap CI (ms) | Added Delay CV | Bulk Goodput Median (Mbps) | Goodput Fraction | Call Loss Median (%) |
|---|---|---|---|---|---|---|---|---|---|
| `R0_no_qos` | 2/2 | **0/2** | 199.54 | 0.03 | [199.508, 199.569] | 0.000 | 95.11 | 95.10% | 0.00% |
| `B1_static_htb` | 2/2 | **2/2** | 20.96 | 3.00 | [17.965, 23.955] | 0.143 | 90.70 | 90.70% | 0.00% |
| `B2a_fq_codel` | 2/2 | **2/2** | 0.54 | 0.54 | [0.0, 1.075] | 1.000 | 87.55 | 87.50% | 0.00% |
| `B2b_cake` | 2/2 | **2/2** | 0.83 | 0.03 | [0.802, 0.855] | 0.032 | 87.24 | 87.20% | 0.00% |

## 2. Safety Contract Adherence

| Arm | Interactive Added Delay Target <= 30 ms | Bulk Floor >= 2.0 Mbps | Status |
|---|---|---|---|
| `R0_no_qos` | FAIL (199.54 ms) | PASS (95.11 Mbps) | **NON-COMPLIANT** |
| `B1_static_htb` | PASS (20.96 ms) | PASS (90.70 Mbps) | **COMPLIANT** |
| `B2a_fq_codel` | PASS (0.54 ms) | PASS (87.55 Mbps) | **COMPLIANT** |
| `B2b_cake` | PASS (0.83 ms) | PASS (87.24 Mbps) | **COMPLIANT** |
