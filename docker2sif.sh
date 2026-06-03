#!/usr/bin bash
container_name=cmrlab/megflow
version=1.0.0
#/opt/singularity-ce/4.1.1/bin/singularity build --sandbox debug_singularity docker-daemon://${container_name}:${version}
# rm -f megflow_1.0.0.sif
/opt/singularity-ce/4.1.1/bin/singularity build ${container_name}_${version}.sif docker-daemon://${container_name}:${version}
