import paramiko

def test_can_connect_to_remote(sshd_container, ssh_key):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        sshd_container["host"],
        port=sshd_container["port"],
        username=sshd_container["user"],
        key_filename=ssh_key["private_path"],
    )
    stdin, stdout, stderr = client.exec_command("echo hello")
    assert stdout.read().decode().strip() == "hello"
    client.close()


def test_workdir_created_on_remote(sshd_container, ssh_key):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        sshd_container["host"],
        port=sshd_container["port"],
        username=sshd_container["user"],
        key_filename=ssh_key["private_path"],
    )
    stdin, stdout, stderr = client.exec_command(f"test -d {sshd_container['workdir']} && echo ok")
    assert stdout.read().decode().strip() == "ok"
    client.close()
