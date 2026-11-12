#ifndef INPUT_TEST_I2C1_H
#define INPUT_TEST_I2C1_H
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
typedef enum
{
    I2C_ERROR_NONE = 0,
    I2C_ERROR_ADDR_NACK,
    I2C_ERROR_DATA_NACK,
    I2C_ERROR_BUS_COLLISION
} i2c_host_error_t;
bool I2C1_Write(uint16_t address, uint8_t *data, size_t length);
bool I2C1_Read(uint16_t address, uint8_t *data, size_t length);
bool I2C1_WriteRead(uint16_t address, uint8_t *writeData, size_t writeLength,
                   uint8_t *readData, size_t readLength);
bool I2C1_IsBusy(void);
i2c_host_error_t I2C1_ErrorGet(void);
void I2C1_CallbackRegister(void (*callback)(void));
#endif
