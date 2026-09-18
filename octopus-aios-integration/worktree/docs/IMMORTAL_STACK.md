# IMMORTAL NODE STACK

## Philosophy

Nodes are disposable. State is immortal.

The swarm must survive:

- process death
- container death
- host death
- region death
- partial network partitions

## Core Loop

```text
state -> execution -> mutation -> propagation -> rehydration -> state
```

## Layers

### 1. Gossip Mesh

Responsibilities:

- peer discovery
- health propagation
- topology repair
- event broadcast

Existing Octopus primitives already include Kademlia DHT and Gossip Protocol. The immortal layer should sit above them instead of replacing them.

### 2. State DAG

Append-only state timeline. Every mutation becomes a commit.

Current MVP:

- local append-only commit timeline
- materialized state snapshot
- deterministic commit hash

Future upgrade:

- CRDT merge
- vector clocks
- causal ordering
- distributed commit persistence

### 3. Ghost Execution

Tasks are executed redundantly across multiple workers.

Goal:

- one worker can die without killing the task
- multiple outputs can be verified
- the system can accept the majority/verified result

Future upgrade:

- quorum selection
- result hashing
- verifier plugins
- speculative execution

### 4. Rehydration

A dead node can reconstruct runtime state from:

- latest snapshot
- state DAG commits
- gossip memory
- peer metadata

This makes node identity disposable.

## Production Deployment

### Minimal production layout

```text
VPS-1: octopus node + redis + nats
VPS-2: octopus node + redis replica + nats
VPS-3: octopus node + snapshot storage worker
```

### Strong production layout

```text
Region EU
  - Kubernetes cluster
  - Octopus pods
  - Redis/NATS
  - snapshot writer

Region US
  - Kubernetes cluster
  - Octopus pods
  - Redis/NATS
  - snapshot mirror

Region ASIA
  - Kubernetes cluster
  - Octopus pods
  - cold standby / edge workers
```

## SCI-FI Grade Target

Final target:

- no permanent node identity
- state-first runtime
- ghost workers
- portable compute
- CRDT memory
- self-repairing topology

In the final form, nodes are only temporary manifestations of distributed state.
