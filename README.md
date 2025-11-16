# PQC vs SECOC-DoS-Evaluation

**Experimental framework comparing SECOC (HMAC-based) and Post-Quantum (CRYSTALS-Dilithium) authentication under high-load / DoS-like conditions.**  
Includes TCP-based ECU simulation, automated stress testing, normalization and performance analysis.

---

## Project Overview  
Modern automotive systems rely on in-vehicle network communication (ECUs exchanging control/sensor data).  
The standard AUTOSAR Secure Onboard Communication (SecOC) module typically uses HMAC for authenticity. Although efficient today, symmetric-key HMAC schemes may become vulnerable in the quantum era.  
This project implements and compares:

- **Classical SecOC (HMAC)** path  
- **Post-Quantum SecOC (PQC, Dilithium2)** path  

Both are evaluated under identical conditions including simulated Denial-of-Service (DoS) traffic, to assess reliability, latency and system resilience.

##  Repository Structure  
├── secoc_sender_tcp.py # Sender for HMAC-based SecOC
├── secoc_receiver_tcp.py # Receiver for HMAC-based SecOC
├── sender_pqc.py # Sender for PQC (Dilithium) path
├── receiver_pqc.py # Receiver for PQC path with threading + adaptive overload control
├── dos_simulator.py # High-concurrency load generator (DoS simulation)
├── run_experiments.sh # Automation script: launches both systems, repeats runs, normalizes + analyzes
├── normalize_results.py # Normalize raw logs to standardized CSV format
├── analyze_runs.py # Generate comparison graphs / summaries from normalized data
└── README.md # This file

##  Setup & Usage  
1. Clone the repository:
   
   git clone https://github.com/AishwaryaPuthuraya/pqc-vs-secoc-dos-evaluation.git
   cd pqc-vs-secoc-dos-evaluation
   
Install dependencies (example):

pip install oqs psutil numpy pandas matplotlib
Adjust configuration as needed (ports, concurrency, PQC workload) in run_experiments.sh.

Run the full experiment:

chmod +x run_experiments.sh
./run_experiments.sh

This launches the HMAC receiver, runs the simulator, then the PQC receiver, repeats the runs, normalizes results and creates comparative output.

View results:

results/ folder: raw logs per run

normalized/ folder: normalized CSVs

analysis/ folder: comparison summaries and graphs

What to Expect

Metrics measured include:

Success rate (%) — how many messages were successfully authenticated

Failures — number of rejected or dropped messages

Latency — mean, p50 (median), p90, p99 values

CPU / load behaviour — especially under DoS conditions

Interpretation:

A high success rate with low latency indicates robust authentication under stress.

Large tail latency (p99) or many failures suggest system overload or crypto bottlenecks.

The PQC-based receiver includes adaptive controls (threading, drop heuristics) to maintain reliability under load.

Why Use This Framework

Research tool for real-time authentication performance in embedded systems

Demonstrates quantum-resilient authentication in an automotive-style context

Useful starting point for engineers, researchers, or teams exploring PQC migration in in-vehicle networks

Contributions & Extensions

Interested in extending the work? Some future directions:

Port to actual automotive ECUs (ARM, AUTOSAR stack)

Test other NIST PQC candidates (e.g., Falcon, SPHINCS+)

Add side-channel or hardware acceleration experiments

Integrate with CAN-FD or automotive Ethernet rather than TCP

Contributions welcome! Feel free to fork this repository, open issues or pull requests. Please ensure your changes maintain clean code, appropriate documentation and no proprietary dependencies.

License

This project is released under the MIT License.
You are free to use, modify, distribute and integrate this code — with attribution.

Contact

For questions or suggestions, please open an issue on this repository
For discussions or feedback, use the GitHub Discussions tab.
