#ifndef SERIAL_TEST_STRING_H
#define SERIAL_TEST_STRING_H
#include <stddef.h>
void *memset(void *dest, int value, size_t length);
size_t strlen(const char *str);
char *strcpy(char *dest, const char *source);
int strcmp(const char *a, const char *b);
int strncmp(const char *a, const char *b, size_t length);
char *strchr(const char *str, int ch);
#endif
