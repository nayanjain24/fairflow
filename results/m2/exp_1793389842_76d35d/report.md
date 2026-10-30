# FairFlow M2 Scenario A Report: scenario_a_baselines

- **Run ID**: `exp_1793389842_76d35d`
- **Mode**: `smoke`
- **Timestamp UTC**: `2026-10-30T19:53:34.029699+00:00`
- **Kernel**: `Linux 6.8 (Ubuntu 24.04 aarch64)`
- **TCP Congestion Control**: `cubic`
- **Contract SHA256**: `04893b27e604b38cd0fb0e6267b307d2f05447fcde333fd73f1743b9d5a499a8`

## 1. Primary & Secondary Metrics Summary

| Arm | Valid Trials | Target Met (k/N) | Added Delay p99 Median (ms) | Added Delay p99 IQR (ms) | 95% Bootstrap CI (ms) | Added Delay CV | Bulk Goodput Median (Mbps) | Goodput Fraction | Call Loss Median (%) |
|---|---|---|---|---|---|---|---|---|---|
| `R0_no_qos` | 2/2 | **0/2** | 199.35 | 0.12 | [199.224, 199.468] | 0.001 | 95.42 | 95.40% | 0.00% |
| `B1_static_htb` | 2/2 | **1/2** | 27.67 | 10.13 | [17.541, 37.799] | 0.366 | 90.81 | 90.80% | 0.00% |
| `B2a_fq_codel` | 2/2 | **2/2** | 1.25 | 0.61 | [0.632, 1.86] | 0.493 | 87.66 | 87.70% | 0.00% |
| `B2b_cake` | 2/2 | **2/2** | 1.24 | 0.32 | [0.919, 1.557] | 0.258 | 87.45 | 87.50% | 0.00% |

## 2. Safety Contract Adherence

| Arm | Interactive Added Delay Target <= 30 ms | Bulk Floor >= 2.0 Mbps | Status |
|---|---|---|---|
| `R0_no_qos` | FAIL (199.35 ms) | PASS (95.42 Mbps) | **NON-COMPLIANT** |
| `B1_static_htb` | PASS (27.67 ms) | PASS (90.81 Mbps) | **COMPLIANT** |
| `B2a_fq_codel` | PASS (1.25 ms) | PASS (87.66 Mbps) | **COMPLIANT** |
| `B2b_cake` | PASS (1.24 ms) | PASS (87.45 Mbps) | **COMPLIANT** |
