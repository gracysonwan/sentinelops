package com.sentinelops.inventory;

import org.springframework.boot.CommandLineRunner;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;

@Service
public class InventoryService implements CommandLineRunner {

    /** Stock is topped up automatically so the load generator can run for hours. */
    static final int RESTOCK_LEVEL = 10_000;

    public record ReserveResult(String productId, double unitPrice, int reserved, int remaining) {
    }

    private final ProductRepository repository;

    public InventoryService(ProductRepository repository) {
        this.repository = repository;
    }

    /** Seed a small catalogue on first start. */
    @Override
    public void run(String... args) {
        if (repository.count() == 0) {
            repository.saveAll(List.of(
                    new Product("P-100", "Wireless Mouse", 799.0, RESTOCK_LEVEL),
                    new Product("P-200", "Mechanical Keyboard", 3499.0, RESTOCK_LEVEL),
                    new Product("P-300", "USB-C Hub", 1899.0, RESTOCK_LEVEL),
                    new Product("P-400", "27-inch Monitor", 15999.0, RESTOCK_LEVEL),
                    new Product("P-500", "Laptop Stand", 1299.0, RESTOCK_LEVEL)));
        }
    }

    @Transactional
    public ReserveResult reserve(String productId, int quantity) {
        if (quantity <= 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "quantity must be positive");
        }
        Product product = repository.findForUpdate(productId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "unknown product " + productId));
        if (product.getStock() < quantity) {
            product.setStock(RESTOCK_LEVEL);
        }
        product.setStock(product.getStock() - quantity);
        return new ReserveResult(product.getId(), product.getUnitPrice(), quantity, product.getStock());
    }

    public List<Product> all() {
        return repository.findAll();
    }
}
