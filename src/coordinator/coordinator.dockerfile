# Dockerfile for scheduler service
FROM python:3.8

WORKDIR /app

# Copy the requirements.txt from the root of the project
COPY /requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the scheduler service code
COPY . .

CMD [ "python", "-m" , "app" ]
