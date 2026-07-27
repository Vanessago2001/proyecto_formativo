import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect(
        host='certisena-iso-ninjaepicoxd-0591.j.aivencloud.com',
        port=22318,
        user='avnadmin',
        password='AVNS_EXrMOMInxkyAHC0ylrq',
        database='defaultdb',
        ssl='require'
    )

    # 1. Obtener el esquema de la tabla usuario
    print('=== ESQUEMA DE LA TABLA usuario ===')
    columns = await conn.fetch('''
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name = 'usuario'
        ORDER BY ordinal_position;
    ''')
    for col in columns:
        print(f'  {col["column_name"]:30s} | {col["data_type"]:25s} | nullable={col["is_nullable"]} | default={col["column_default"]}')

    # 2. Obtener los constraints de la tabla usuario
    print()
    print('=== CONSTRAINTS DE LA TABLA usuario ===')
    constraints = await conn.fetch('''
        SELECT conname, contype, pg_get_constraintdef(oid) as definition
        FROM pg_constraint
        WHERE conrelid = 'usuario'::regclass;
    ''')
    for con in constraints:
        print(f'  {con["conname"]:30s} | type={con["contype"]} | {con["definition"]}')

    # 3. Obtener los datos del usuario admin
    print()
    print('=== DATOS DEL USUARIO Administrador ===')
    user = await conn.fetchrow('SELECT * FROM usuario WHERE nombre = $1;', 'Administrador')
    if user:
        for key, value in user.items():
            print(f'  {key:30s} = {value}')
    else:
        print('  No se encontro el usuario Administrador')

    await conn.close()

asyncio.run(main())
