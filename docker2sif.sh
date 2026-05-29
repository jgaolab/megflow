#!/usr/bin bash
container_name=megflow
version=0.0.3
#/opt/singularity-ce/4.1.1/bin/singularity build --sandbox debug_singularity docker-daemon://${container_name}:${version}
rm -f megflow_0.0.3.sif
/opt/singularity-ce/4.1.1/bin/singularity build ${container_name}_${version}.sif docker-daemon://${container_name}:${version}
