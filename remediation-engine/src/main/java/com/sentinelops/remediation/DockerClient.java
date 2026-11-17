package com.sentinelops.remediation;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.StandardProtocolFamily;
import java.net.UnixDomainSocketAddress;
import java.nio.ByteBuffer;
import java.nio.channels.SocketChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Minimal Docker Engine API client over the Unix socket (/var/run/docker.sock), using only the JDK.
 * The remediation container gets the socket mounted by Docker Compose, which lets it restart its
 * sibling containers. Works the same on Linux and on Docker Desktop for Windows/macOS.
 */
public class DockerClient {

    private final Path socketPath;

    public DockerClient(String socketPath) {
        this.socketPath = Path.of(socketPath);
    }

    public boolean isAvailable() {
        return Files.exists(socketPath);
    }

    /**
     * POST /containers/{name}/restart?t={timeout}. Docker answers 204 when the container was restarted.
     *
     * @return the HTTP status code returned by the Docker daemon
     */
    public int restart(String containerName, int stopTimeoutSeconds) throws IOException {
        return post("/containers/" + containerName + "/restart?t=" + stopTimeoutSeconds);
    }

    int post(String path) throws IOException {
        String request = "POST " + path + " HTTP/1.1\r\n"
                + "Host: docker\r\n"
                + "Content-Length: 0\r\n"
                + "Connection: close\r\n\r\n";
        try (SocketChannel channel = SocketChannel.open(StandardProtocolFamily.UNIX)) {
            channel.connect(UnixDomainSocketAddress.of(socketPath));
            ByteBuffer out = ByteBuffer.wrap(request.getBytes(StandardCharsets.US_ASCII));
            while (out.hasRemaining()) {
                channel.write(out);
            }
            ByteArrayOutputStream response = new ByteArrayOutputStream();
            ByteBuffer in = ByteBuffer.allocate(4096);
            while (channel.read(in) > 0) {
                in.flip();
                response.write(in.array(), 0, in.limit());
                in.clear();
            }
            return parseStatus(response.toString(StandardCharsets.US_ASCII));
        }
    }

    /** "HTTP/1.1 204 No Content" -> 204. */
    static int parseStatus(String rawResponse) throws IOException {
        int lineEnd = rawResponse.indexOf("\r\n");
        String statusLine = lineEnd >= 0 ? rawResponse.substring(0, lineEnd) : rawResponse;
        String[] parts = statusLine.split(" ");
        if (parts.length < 2 || !parts[0].startsWith("HTTP/")) {
            throw new IOException("Unexpected Docker API response: " + statusLine);
        }
        try {
            return Integer.parseInt(parts[1]);
        } catch (NumberFormatException e) {
            throw new IOException("Unexpected Docker API status line: " + statusLine, e);
        }
    }
}
