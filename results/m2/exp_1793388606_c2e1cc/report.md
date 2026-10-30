# FairFlow M2 Scenario A Report: scenario_a_baselines

- **Run ID**: `exp_1793388606_c2e1cc`
- **Mode**: `smoke`
- **Timestamp UTC**: `2026-10-30T19:32:58.629422+00:00`
- **Kernel**: `Linux 6.8 (Ubuntu 24.04 aarch64)`
- **TCP Congestion Control**: `cubic`
- **Contract SHA256**: `04893b27e604b38cd0fb0e6267b307d2f05447fcde333fd73f1743b9d5a499a8`

## 1. Primary & Secondary Metrics Summary

| Arm | Valid Trials | Target Met (k/N) | Added Delay p99 Median (ms) | Added Delay p99 IQR (ms) | 95% Bootstrap CI (ms) | Added Delay CV | Bulk Goodput Median (Mbps) | Goodput Fraction | Call Loss Median (%) |
|---|---|---|---|---|---|---|---|---|---|
| `R0_no_qos` | 2/2 | **0/2** | 199.44 | 0.00 | [199.439, 199.444] | 0.000 | 95.31 | 95.30% | 0.00% |
| `B1_static_htb` | 2/2 | **2/2** | 17.45 | 7.49 | [9.959, 24.933] | 0.429 | 90.81 | 90.80% | 0.00% |
| `B2a_fq_codel` | 2/2 | **2/2** | 2.59 | 1.88 | [0.708, 4.474] | 0.727 | 87.55 | 87.60% | 0.00% |
| `B2b_cake` | 2/2 | **2/2** | 0.76 | 0.08 | [0.681, 0.838] | 0.103 | 87.34 | 87.30% | 0.00% |

## 2. Safety Contract Adherence

| Arm | Interactive Added Delay Target <= 30 ms | Bulk Floor >= 2.0 Mbps | Status |
|---|---|---|---|
| `R0_no_qos` | FAIL (199.44 ms) | PASS (95.31 Mbps) | **NON-COMPLIANT** |
| `B1_static_htb` | PASS (17.45 ms) | PASS (90.81 Mbps) | **COMPLIANT** |
| `B2a_fq_codel` | PASS (2.59 ms) | PASS (87.55 Mbps) | **COMPLIANT** |
| `B2b_cake` | PASS (0.76 ms) | PASS (87.34 Mbps) | **COMPLIANT** |
