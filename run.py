from app import create_app

app = create_app() # chama a construção do aplicativo

if __name__ == '__main__':
    app.run(debug=True) # inicia o servidor 
