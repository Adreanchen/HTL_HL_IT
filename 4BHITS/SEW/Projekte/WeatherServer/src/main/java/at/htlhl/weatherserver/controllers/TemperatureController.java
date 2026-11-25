package at.htlhl.weatherserver.controllers;

import at.htlhl.weatherserver.model.Temperature;
import at.htlhl.weatherserver.repositories.TemperatureRepository;
import io.swagger.v3.oas.annotations.Operation;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/weatherserver/temperature")
public class TemperatureController {
    private TemperatureRepository repository;

    public TemperatureController(TemperatureRepository repository) {
        this.repository = repository;
    }

    @GetMapping("")
    @Operation(summary = "get latest temperature")
    public ResponseEntity<Temperature> findLatest() {
        Temperature latestTemperature = repository.findLatesTemperature();
        if(latestTemperature == null) {
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.ok(latestTemperature);
    }
}
