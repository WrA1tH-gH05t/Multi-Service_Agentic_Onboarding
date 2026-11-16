import psycopg2, os

conn = psycopg2.connect('postgresql://intake:intake_secret_2026@localhost:5432/doc_intake')
cur = conn.cursor()
cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'users';")
for col in cur.fetchall():
    print(col)
cur.execute('SELECT * FROM users;')
cols = [desc[0] for desc in cur.description]
print('Columns:', cols)
for row in cur.fetchall():
    print(dict(zip(cols, row)))
