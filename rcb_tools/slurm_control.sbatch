#!/bin/bash
#SBATCH --job-name=rcb-ctrl
#SBATCH --partition=eval
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/ctrl-%x-%j.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/ctrl-%x-%j.out

# One control task per job, on the eval partition, off the login/a3 node.
#
# Everything this needs is already on shared storage: the claude CLI and ~/rcb_tools on NFS
# home, the ResearchClawBench checkout and the workspaces on /rmeng_data. Vertex auth comes
# from the node's own metadata-server credentials, not from an ADC file -- verified by
# running a real claude call on slurm2-c3smallnodeset-26 and getting provider=vertex,
# canonicalModel=claude-opus-5 back.
#
# The command is `run_arm.py control <TASK>`, the same launcher and the same agent command
# the local batch uses. A one-off script here is how two halves of one arm silently stop
# being comparable.
set -u
TASK="${1:?usage: sbatch slurm_control.sbatch <TASK_ID>}"
echo "[$(date '+%F %T')] node=$(hostname) cpus=$(nproc) task=$TASK"
exec python3 /home/robtang_google_com/rcb_tools/run_arm.py control "$TASK"
