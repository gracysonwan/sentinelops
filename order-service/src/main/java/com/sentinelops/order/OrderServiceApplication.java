package com.sentinelops.order;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/** Scans com.sentinelops so the shared chaos module (com.sentinelops.chaos) is picked up. */
@SpringBootApplication(scanBasePackages = "com.sentinelops")
public class OrderServiceApplication {
    public static void main(String[] args) {
        SpringApplication.run(OrderServiceApplication.class, args);
    }
}
