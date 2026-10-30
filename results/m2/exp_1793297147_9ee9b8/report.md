# FairFlow M2 Scenario A Report: scenario_a_baselines

- **Run ID**: `exp_1793297147_9ee9b8`
- **Mode**: `smoke`
- **Timestamp UTC**: `2026-10-29T18:08:57.615806+00:00`
- **Kernel**: `Linux 6.8 (Ubuntu 24.04 aarch64)`
- **TCP Congestion Control**: `cubic`
- **Contract SHA256**: `04893b27e604b38cd0fb0e6267b307d2f05447fcde333fd73f1743b9d5a499a8`

## 1. Primary & Secondary Metrics Summary

| Arm | Valid Trials | Target Met (k/N) | Added Delay p99 Median (ms) | Added Delay p99 IQR (ms) | 95% Bootstrap CI (ms) | Added Delay CV | Bulk Goodput Median (Mbps) | Goodput Fraction | Call Loss Median (%) |
|---|---|---|---|---|---|---|---|---|---|
| `R0_no_qos` | 2/2 | **0/2** | 198.21 | 1.09 | [197.113, 199.3] | 0.005 | 95.00 | 95.00% | 0.00% |
| `B1_static_htb` | 2/2 | **0/2** | 62.53 | 11.83 | [50.698, 74.365] | 0.189 | 89.03 | 89.00% | 0.00% |
| `B2a_fq_codel` | 2/2 | **2/2** | 5.03 | 2.67 | [2.365, 7.697] | 0.530 | 85.67 | 85.70% | 0.00% |
| `B2b_cake` | 2/3 | **2/3** | 4.09 | 1.80 | [2.285, 5.889] | 0.441 | 86.72 | 86.70% | 0.00% |

## 2. Safety Contract Adherence

| Arm | Interactive Added Delay Target <= 30 ms | Bulk Floor >= 2.0 Mbps | Status |
|---|---|---|---|
| `R0_no_qos` | FAIL (198.21 ms) | PASS (95.00 Mbps) | **NON-COMPLIANT** |
| `B1_static_htb` | FAIL (62.53 ms) | PASS (89.03 Mbps) | **NON-COMPLIANT** |
| `B2a_fq_codel` | PASS (5.03 ms) | PASS (85.67 Mbps) | **COMPLIANT** |
| `B2b_cake` | PASS (4.09 ms) | PASS (86.72 Mbps) | **COMPLIANT** |
