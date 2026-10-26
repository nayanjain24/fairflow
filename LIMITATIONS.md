# FairFlow: Limitations & Scope Constraints

This document records architectural, topological, and evaluation limitations of the FairFlow research testbed in Milestone 2 (M2) and beyond.

---

### 1. Software Emulation Only
The testbed is fully emulated in Linux network namespaces (`ff_client`, `ff_router`, `ff_server`) interconnected by virtual Ethernet (`veth`) pairs on a single Ubuntu 24.04 ARM64 kernel (Linux 6.8). Network delays and rate limits are produced using `sch_netem` and `sch_tbf` rather than real physical links, optical/copper transceivers, or electrical line attenuation.

### 2. Unshaped TCP ACK Path
In Scenario A, the contested direction is downstream: `server -> router -> client`.
While downstream data flows through the ISP bottleneck on `ff_s_wan` and home QoS on `ff_r_lan`, TCP acknowledgments (ACKs) flowing upstream (`client -> router -> server`) traverse `ff_r_wan` with propagation delay (`netem delay 15ms`) but are **not shaped or rate-limited** in v1. In asymmetrical broadband links (e.g., DOCSIS cable or VDSL with narrow upstream channels), ACK compression and upstream bufferbloat can degrade downstream throughput; this phenomenon is intentionally omitted from v1.

### 3. True Bottleneck Capacity Known to Baselines
In M2, the baseline QoS arms (`B1_static_htb`, `B2a_fq_codel`, `B2b_cake`) are configured using the *true, known* laboratory bottleneck capacity ($100.0\text{ Mbps} \times 0.95 = 95.0\text{ Mbps}$). In real residential deployments, the router does not know the exact instantaneous ISP provisioning rate and must estimate it dynamically (addressed in M3). Providing true capacity represents a best-case advantage for the static baselines.

### 4. Single TCP Congestion Control Algorithm
Bulk download traffic in M2 uses standard Linux TCP Cubic (`net.ipv4.tcp_congestion_control = cubic`). Different congestion control algorithms (such as BBRv1/v2/v3, Reno, or DCTCP) exhibit different queue-filling behaviors, loss sensitivities, and RTT-fairness properties.

### 5. Synthetic Deterministic Call Traffic
The interactive call simulator transmits fixed 160-byte UDP payloads at rigid 20 ms intervals (50 packets/s), modeled on uncompressed G.711 / Opus voice frames. Real conversational traffic includes variable bitrate (VBR) codecs, discontinuous transmission (DTX), silence suppression (comfort noise), forward error correction (FEC), and video keyframe bursts.

### 6. Single VM Host & Shared Hardware Resources
All namespaces run on the same virtualized host kernel inside a Multipass VM sharing CPU caches, system memory bus, and kernel packet scheduler queues. Although processes are pinned to separate vCPUs via `taskset`, cross-core cache invalidation and hypervisor scheduling jitter may introduce minor artifacts not present across physically separated hardware nodes.

### 7. Absence of Physical Home-Router Hardware
Commodity home routers run embedded MIPS/ARM SoCs with limited CPU budgets, constrained ring buffers, network acceleration engines (flow offloading / shortcut forwarding), and proprietary wireless drivers. Software namespaces on high-performance virtualization do not model embedded CPU exhaustion under line-rate shaping.
