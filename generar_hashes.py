from core.security import hash_password

usuarios = {
    "gerente@empresa.com": "Gerente123",
    "empleado1@empresa.com": "Empleado123",
    "empleado2@empresa.com": "Empleado456",
    "auditor1@empresa.com": "Auditor123",
    "auditor2@empresa.com": "Auditor456",
    "empresa1@empresa.com": "Empresa123",
    "empresa2@empresa.com": "Empresa456",
    "admin@empresa.com": "Admin123",
}

print("\n===== HASHES =====\n")

for correo, password in usuarios.items():
    print(f"{correo}")
    print(hash_password(password))
    print("-" * 80)