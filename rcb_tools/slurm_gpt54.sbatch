#!/bin/bash
#SBATCH --job-name=autor54
#SBATCH --partition=eval
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=28G
#SBATCH --time=24:00:00
#SBATCH --array=1-40%40
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/g54-%a-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/g54-%a-%A.out

# AutoR on gpt-5.4, one task per job, to sit against the leaderboard's published
# Codex CLI (GPT-5.4) = 18.42 -- the same scaffold-versus-bare-agent question the Opus 5
# pair asks, at a model the leaderboard already has a bare-agent number for, and with
# codex as the harness on both sides.
#
# The route to gpt-5.4 is `codex-rcb`, a wrapper with its own CODEX_HOME. This machine's
# ~/.codex is not read and not written; it keeps its own model. The key reaches codex as an
# environment variable resolved through `env_key`, so it never lands in a config file, a
# command line or a job log.
#
# Sandbox stays at workspace-write. Search is codex's own `web_search`, served by the
# Responses API, so the arm gets search without the sandbox being opened.
set -u
TASK=$(sed -n "${SLURM_ARRAY_TASK_ID}p" /home/robtang_google_com/rcb_tools/tasks40.txt)
echo "[$(date '+%F %T')] node=$(hostname) cpus=$(nproc) task=$TASK"
exec python3 /home/robtang_google_com/rcb_tools/run_arm.py autor_gpt54 "$TASK"
