# Use the official PHP image with Apache as the base image
FROM php:8.2-apache

# Install required PHP extensions for Grav
RUN apt-get update \
    && apt-get install -y libpng-dev libjpeg-dev libfreetype6-dev \
    && docker-php-ext-configure gd --with-freetype --with-jpeg \
    && docker-php-ext-install gd pdo pdo_mysql


RUN apt-get update && apt-get install -y unzip \
    libzip-dev \
    && rm -rf /var/lib/apt/lists/*


# Install PHP extensions
RUN docker-php-ext-install zip    

# Install Composer
RUN curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer

# Copy the Grav site files into the container
COPY . /var/www/html/

RUN mkdir -p /var/www/html/images
RUN mkdir -p /var/www/html/backup
RUN mkdir -p /var/www/html/logs
RUN mkdir -p /var/www/html/tmp
RUN mkdir -p /var/www/html/assets

# Run Composer install
RUN composer install --no-dev --no-interaction --no-scripts

# Set the correct permissions for Grav
RUN chown -R www-data:www-data /var/www/html/

# Force exactly one MPM (mod_php needs prefork). The base image may ship
# mpm_event enabled; a2dismod can no-op silently, so delete the event/worker
# module symlinks outright, then enable prefork. Fail the build (apache2ctl -t)
# if more than one MPM is still loaded, instead of crash-looping at runtime
# with "AH00534: apache2: Configuration error: More than one MPM loaded."
RUN a2dismod mpm_event mpm_worker 2>/dev/null || true; \
    rm -f /etc/apache2/mods-enabled/mpm_event.* /etc/apache2/mods-enabled/mpm_worker.*; \
    a2enmod mpm_prefork rewrite; \
    apache2ctl -t

# This image runs only as the throwaway Grav backend for the static export
# (tools/build-static.sh builds it, serves it on 127.0.0.1, and crawls it).
EXPOSE 80

# Single MPM (mod_php prefork) is enforced + build-verified above; just start.
CMD ["apache2-foreground"]

