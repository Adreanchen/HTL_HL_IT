package at.htlhl.weatherserver.model;

import java.time.LocalDateTime;

public class Temperature {
    private long id;
    private LocalDateTime measureTime;
    private float temp;

    public Temperature() {
    }

    public long getId() {
        return id;
    }

    public LocalDateTime getMeasureTime() {
        return measureTime;
    }

    public float getTemp() {
        return temp;
    }

    public void setId(long id) {
        this.id = id;
    }

    public void setMeasureTime(LocalDateTime measureTime) {
        this.measureTime = measureTime;
    }

    public void setTemp(float temp) {
        this.temp = temp;
    }

    @Override
    public String toString() {
        return "Temperature: " + "id=" + id + ", measureTime=" + measureTime + ", temp=" + temp;
    }

}