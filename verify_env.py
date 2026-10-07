#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys

print('=== Verificando entorno para correr el archivo ===')
print()

# 1. Verificar run.py
print('1. Archivo run.py:')
if os.path.exists('run.py'):
    print('   OK - Existe')
    with open('run.py', 'r') as f:
        content = f.read()
    print('   Tamaño: {} caracteres'.format(len(content)))
else:
    print('   FALTANTE - NO EXISTE')

# 2. Verificar dependencias básicas
print()
print('2. Dependencias mínimas:')
deps = ['flask', 'python-dotenv', 'google-genai']
for dep in deps:
    try:
        __import__(dep)
        print('   OK - {}'.format(dep))
    except ImportError:
        print('   FALTANTE - {}'.format(dep))

# 3. Verificar app factory
print()
print('3. App factory (app/__init__.py):')
if os.path.exists('app/__init__.py'):
    print('   OK - Existe')
else:
    print('   FALTANTE - NO EXISTE')

# 4. Verificar estado/seed
print()
print('3. Datos y configuración:')
if os.path.exists('app/seed_data.json'):
    print('   OK - seed_data.json existe')
else:
    print('   FALTANTE - seed_data.json NO EXISTE')

if os.path.exists('.env.example'):
    print('   OK - .env.example existe')
else:
    print('   FALTANTE - .env.example NO EXISTE')

# 5. Verificar templates
print()
print('4. Templates principales:')
for t in ['templates/base.html', 'templates/login.html']:
    if os.path.exists('templates/{}'.format(t)):
        print('   OK - {} existe'.format(t))
    else:
        print('   FALTANTE - {} NO EXISTE'.format(t))

print()
print('=== Resumen ===')
print('Para correr: python run.py')
print('Necesitas: Flask instalado, .env configurado (opcional), seed_data.json')