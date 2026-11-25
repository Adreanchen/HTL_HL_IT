package at.htlhl.weatherserver.controllers;

import at.htlhl.weatherserver.repositories.TemperatureRepository;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/weatherserver/temperature")
public class TemperatureController {
    private TemperatureRepository temperatureRepository;

    public TemperatureController(TemperatureRepository temperatureRepository) {
        this.temperatureRepository = temperatureRepository;
    }

    public 
}
