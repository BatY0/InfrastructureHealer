import docker
import time
import subprocess

client = docker.from_env()

def create_cluster():
    """
    Creates a sandboxed k3d cluster.
    Assumes k3d is installed and available in the system PATH.
    """
    print("Creating k3d cluster 'healer-sandbox'...")
    try:
        subprocess.run(["k3d", "cluster", "create", "healer-sandbox"], check=True)
        print("Cluster created successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to create cluster. Ensure k3d is installed. Error: {e}")

def destroy_cluster():
    """`
    Destroys the sandboxed k3d cluster.
    """
    print("Destroying k3d cluster 'healer-sandbox'...")
    try:
        subprocess.run(["k3d", "cluster", "delete", "healer-sandbox"], check=True)
        print("Cluster destroyed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to destroy cluster. Error: {e}")

def list_containers():
    """
    Lists all Docker containers related to the sandbox.
    """
    containers = client.containers.list(filters={"name": "k3d-healer-sandbox"})
    for container in containers:
        print(f"ID: {container.short_id}, Name: {container.name}, Status: {container.status}")
    return containers

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == "create":
            create_cluster()
        elif sys.argv[1] == "destroy":
            destroy_cluster()
        elif sys.argv[1] == "status":
            list_containers()
    else:
        print("Usage: python sandbox.py [create|destroy|status]")
