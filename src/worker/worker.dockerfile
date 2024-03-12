# Use an official Golang runtime as a parent image
FROM golang:1.20

# Set the working directory to /app
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . .

# Install any needed packages specified in go.mod and go.sum
RUN go mod download

# Build the worker binary
RUN go build -o worker .

# Set the command to run when starting the container
CMD ["./worker"]
