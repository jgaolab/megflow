#!/bin/bash  

IMAGE_NAME=cmrlab/megflow
VERSION="1.0.0"
DOCKERFILE_NAME=megflow.Dockerfile 


if [[ ! -f "$DOCKERFILE_NAME" ]]; then  
    echo "Error: Dockerfile not found at $DOCKERFILE_NAME"  
    exit 1  
fi  


echo "Building Docker image: $IMAGE_NAME using Dockerfile at $DOCKERFILE_NAME..."  
docker build -t "$IMAGE_NAME:$VERSION" -f "$DOCKERFILE_NAME" .


if [[ $? -eq 0 ]]; then  
    echo "Docker image $IMAGE_NAME built successfully."  
else  
    echo "Error: Docker image $IMAGE_NAME failed to build."  
    exit 1  
fi
