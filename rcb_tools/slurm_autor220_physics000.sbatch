#!/bin/bash
#SBATCH --job-name=autor220b
#SBATCH --partition=eval
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=31G
#SBATCH --time=40:00:00
#SBATCH --array=1-1%1
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/autor-%a-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/autor-%a-%A.out

# AutoR over all 40 ResearchClawBench tasks, one task per node, on the eval partition.
#
# This is the clean single-version run. Everything is pinned:
#   code      /home/robtang_google_com/autor-pinned, detached at one commit, clean tree
#   checkout  /rmeng_data/robtang/rcb/ResearchClawBench
#   outputs   /rmeng_data/robtang/rcb_runs/full40
# and every run stamps `code_version` into its own _meta.json, so the artifacts say which
# code produced them rather than relying on this comment.
#
# Verified on an eval node before submitting: code_version resolves, and the Gemini web
# search backend reports no hard blocker (Vertex auth comes from the node's metadata
# server, not an ADC file).
#
# 4 CPUs / 28G, not 8 / 32G: c3smallnodeset is 4 CPUs and 31 GB and 32 of them sit idle,
# so the larger request fit only the seven busy c3nodeset machines and 37 of 40 array
# elements queued behind three. The bottleneck here is the model API -- 66% of wall clock
# was API time on the control arm -- so trading local cores for 32 more nodes is the right
# way round.
#
# 24h per task against a measured median of 11.75h. One task per array element rather than
# a concurrency-capped batch: quota is not the binding constraint here, so wall clock is
# set by the slowest single task instead of by the queue.
set -u
TASK=Physics_000
echo "[$(date '+%F %T')] node=$(hostname) cpus=$(nproc) task=$TASK"
exec python3 /home/robtang_google_com/rcb_tools/run_arm.py autor_v220 "$TASK"
