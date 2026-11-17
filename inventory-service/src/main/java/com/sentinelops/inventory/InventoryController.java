package com.sentinelops.inventory;

import com.sentinelops.inventory.InventoryService.ReserveResult;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/inventory")
public class InventoryController {

    public record ReserveRequest(String productId, int quantity) {
    }

    private final InventoryService inventory;

    public InventoryController(InventoryService inventory) {
        this.inventory = inventory;
    }

    @GetMapping
    public List<Product> all() {
        return inventory.all();
    }

    @PostMapping("/reserve")
    public ReserveResult reserve(@RequestBody ReserveRequest request) {
        return inventory.reserve(request.productId(), request.quantity());
    }
}
