# FairFlow M2 Scenario A Report: scenario_a_baselines

- **Run ID**: `smoke_20261029_174600`
- **Mode**: `smoke`
- **Timestamp UTC**: `2026-10-29T17:48:52.765196+00:00`
- **Kernel**: `Linux 6.8 (Ubuntu 24.04 aarch64)`
- **TCP Congestion Control**: `cubic`
- **Contract SHA256**: `04893b27e604b38cd0fb0e6267b307d2f05447fcde333fd73f1743b9d5a499a8`

## 1. Primary & Secondary Metrics Summary

| Arm | Valid Trials | Target Met (k/N) | Added Delay p99 Median (ms) | Added Delay p99 IQR (ms) | 95% Bootstrap CI (ms) | Added Delay CV | Bulk Goodput Median (Mbps) | Goodput Fraction | Call Loss Median (%) |
|---|---|---|---|---|---|---|---|---|---|
| `R0_no_qos` | 2/2 | **0/2** | 197.98 | 1.46 | [196.52, 199.442] | 0.007 | 95.32 | 95.30% | 0.00% |
| `B1_static_htb` | 2/2 | **1/2** | 36.46 | 8.82 | [27.643, 45.278] | 0.242 | 90.49 | 90.50% | 0.00% |
| `B2a_fq_codel` | 2/2 | **2/2** | 1.51 | 0.71 | [0.798, 2.218] | 0.471 | 88.17 | 88.20% | 0.00% |
| `B2b_cake` | 2/2 | **2/2** | 1.56 | 0.78 | [0.775, 2.343] | 0.503 | 87.24 | 87.20% | 0.00% |

## 2. Safety Contract Adherence

| Arm | Interactive Added Delay Target <= 30 ms | Bulk Floor >= 2.0 Mbps | Status |
|---|---|---|---|
| `R0_no_qos` | FAIL (197.98 ms) | PASS (95.32 Mbps) | **NON-COMPLIANT** |
| `B1_static_htb` | FAIL (36.46 ms) | PASS (90.49 Mbps) | **NON-COMPLIANT** |
| `B2a_fq_codel` | PASS (1.51 ms) | PASS (88.17 Mbps) | **COMPLIANT** |
| `B2b_cake` | PASS (1.56 ms) | PASS (87.24 Mbps) | **COMPLIANT** |
