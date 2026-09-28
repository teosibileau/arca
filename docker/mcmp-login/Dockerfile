# Login con clave fiscal en Mis Comprobantes. Es lo único que necesita un browser:
# el portal abre el servicio con un POST de formulario que fija cookies de sesión.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy
WORKDIR /app
RUN pip install --no-cache-dir playwright==1.47.0 && mkdir /out
COPY login.py .
ENTRYPOINT ["python", "login.py"]
