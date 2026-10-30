# FairFlow M2 Scenario A Report: scenario_a_baselines

- **Run ID**: `exp_1793296469_31c446`
- **Mode**: `smoke`
- **Timestamp UTC**: `2026-10-29T17:57:22.272869+00:00`
- **Kernel**: `Linux 6.8 (Ubuntu 24.04 aarch64)`
- **TCP Congestion Control**: `cubic`
- **Contract SHA256**: `04893b27e604b38cd0fb0e6267b307d2f05447fcde333fd73f1743b9d5a499a8`

## 1. Primary & Secondary Metrics Summary

| Arm | Valid Trials | Target Met (k/N) | Added Delay p99 Median (ms) | Added Delay p99 IQR (ms) | 95% Bootstrap CI (ms) | Added Delay CV | Bulk Goodput Median (Mbps) | Goodput Fraction | Call Loss Median (%) |
|---|---|---|---|---|---|---|---|---|---|
| `R0_no_qos` | 2/2 | **0/2** | 198.29 | 1.01 | [197.276, 199.295] | 0.005 | 95.00 | 95.00% | 0.00% |
| `B1_static_htb` | 2/2 | **2/2** | 16.12 | 5.73 | [10.387, 21.845] | 0.355 | 90.80 | 90.80% | 0.00% |
| `B2a_fq_codel` | 2/2 | **2/2** | 0.84 | 0.07 | [0.774, 0.915] | 0.084 | 87.55 | 87.50% | 0.00% |
| `B2b_cake` | 2/2 | **2/2** | 0.83 | 0.02 | [0.81, 0.853] | 0.026 | 87.35 | 87.30% | 0.00% |

## 2. Safety Contract Adherence

| Arm | Interactive Added Delay Target <= 30 ms | Bulk Floor >= 2.0 Mbps | Status |
|---|---|---|---|
| `R0_no_qos` | FAIL (198.29 ms) | PASS (95.00 Mbps) | **NON-COMPLIANT** |
| `B1_static_htb` | PASS (16.12 ms) | PASS (90.80 Mbps) | **COMPLIANT** |
| `B2a_fq_codel` | PASS (0.84 ms) | PASS (87.55 Mbps) | **COMPLIANT** |
| `B2b_cake` | PASS (0.83 ms) | PASS (87.35 Mbps) | **COMPLIANT** |
